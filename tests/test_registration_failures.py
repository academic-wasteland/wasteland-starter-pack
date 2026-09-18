"""Failed imports must not corrupt previously registered provider snapshots."""
import copy
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wasteland.client import RemoteError
from wasteland.fair import Index, digest, document, fetch_catalogue
from wasteland.fair_city import answer


class RegistrationFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.index = Index(Path(self.temp.name)/'index.sqlite')
        self.doc = json.loads((Path(__file__).resolve().parents[1]/'examples/fair/ubar.jsonld').read_text())
        self.index.ingest('ubar', self.doc, registration=True)
        self.receipt = self.index.registration('ubar')
        self.snapshot = self.index.search()

    def test_failed_registration_keeps_snapshot_and_receipt(self):
        message = {'from':'ubar','body':{'operation':'fair-register','revision':digest(self.doc)}}
        config = {'fair_index':str(self.index.path),'fair_state':self.temp.name}
        for error in (RemoteError('offline'), ValueError('changed revision'), KeyError('catalogue'), OSError('interrupted')):
            with self.subTest(error=type(error).__name__), patch('wasteland.fair_city.Client'), patch('wasteland.fair_city.fetch_catalogue',side_effect=error):
                result = answer(message,config)
                self.assertFalse(result['ok'])
                self.assertEqual(self.index.search(),self.snapshot)
                self.assertEqual(self.index.registration('ubar'),self.receipt)

    def test_atomic_rollback_when_storage_fails_mid_snapshot(self):
        with closing(self.index.connect()) as db, db:
            db.execute("CREATE TRIGGER reject_records BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'simulated disk transaction failure'); END")
        changed=copy.deepcopy(self.doc)
        changed['@graph'][0]['version']='new version'
        with self.assertRaises(sqlite3.IntegrityError):
            self.index.ingest('ubar',changed,registration=True)
        self.assertEqual(self.index.search(),self.snapshot)
        self.assertEqual(self.index.registration('ubar'),self.receipt)
        self.assertEqual(len(self.index.revisions(changed['@graph'][0]['@id'])),1)

    def test_repeated_registration_and_harvest_do_not_rewrite_receipt_history(self):
        self.index.ingest('ubar',self.doc,registration=True)
        receipt=self.index.registration('ubar')
        self.assertEqual(receipt['revision'],self.receipt['revision'])
        self.assertEqual(len(self.index.revisions(self.doc['@graph'][0]['@id'])),1)
        changed=copy.deepcopy(self.doc)
        changed['@graph'][0]['version']='harvest update'
        self.index.ingest('ubar',changed)
        self.assertEqual(self.index.registration('ubar'),receipt)
        self.assertEqual(len(self.index.revisions(changed['@graph'][0]['@id'])),2)
        reopened=Index(self.index.path)
        self.assertEqual(reopened.registration('ubar'),receipt)

    def test_malformed_registration_never_contacts_a_provider(self):
        bad_bodies=[{}, {'revision':None}, {'revision':'not-a-digest'}, {'revision':True},
                    {'revision':digest(self.doc),'owner':'yamatai'},
                    {'revision':digest(self.doc),'url':'https://example.invalid/private'},
                    {'revision':digest(self.doc),'catalogue':self.doc}]
        config={'fair_index':str(self.index.path),'fair_state':self.temp.name}
        with patch('wasteland.fair_city.Client') as client:
            for body in bad_bodies:
                with self.subTest(body=body):
                    result=answer({'from':'ubar','body':{'operation':'fair-register',**body}},config)
                    self.assertFalse(result['ok'])
            client.assert_not_called()
        self.assertEqual(self.index.registration('ubar'),self.receipt)

    def test_receipt_is_scoped_to_authenticated_caller(self):
        config={'fair_index':str(self.index.path)}
        result=answer({'from':'yamatai','body':{'operation':'fair-registration','owner':'ubar'}},config)
        self.assertIsNone(result['registration'])
        self.assertEqual(answer({'from':'ubar','body':{'operation':'fair-registration'}},config)['registration'],self.receipt)

    def test_invalid_pages_and_unrelated_replies_rejected(self):
        doc=self.doc
        class Pages:
            def __init__(self,mutate): self.mutate=mutate; self.calls=0
            def ask(self,owner,**kwargs):
                assert owner=='ubar' and kwargs['operation']=='fair-catalogue'
                self.offset=kwargs['body']['offset']; return 'request-'+str(self.calls)
            def wait(self,mid,*args,**kwargs):
                i=self.offset
                body={'ok':True,'catalogue':document([doc['@graph'][i]]),'revision':digest(doc),
                      'next_offset':i+1 if i+1<len(doc['@graph']) else None}
                reply={'from':'ubar','kind':'answer','in_reply_to':mid,'id':'reply-'+str(i),'body':body}
                self.mutate(reply,i); self.calls+=1
                return [reply]
            def call(self,route,body): assert route=='/v1/ack'
        changes=[lambda r,i:r.update({'from':'yamatai'}),
                 lambda r,i:r.update({'in_reply_to':'unrelated'}),
                 lambda r,i:r.update({'kind':'notice'}),
                 lambda r,i:r['body'].update({'revision':'sha256:'+'f'*64}) if i else None,
                 lambda r,i:r['body'].update({'next_offset':True}),
                 lambda r,i:r['body'].update({'next_offset':0}),
                 lambda r,i:r['body'].update({'next_offset':101}),
                 lambda r,i:r['body'].update({'next_offset':None}),
                 lambda r,i:r['body']['catalogue'].update({'@context':'https://evil.invalid/context'})]
        for change in changes:
            with self.subTest(change=changes.index(change)), self.assertRaises(ValueError):
                fetch_catalogue(Pages(change),'ubar',expected_revision=digest(doc))
        with patch('wasteland.fair.time.monotonic',side_effect=[0,91]):
            with self.assertRaisesRegex(ValueError,'90 seconds'):
                fetch_catalogue(Pages(lambda r,i:None),'ubar')
