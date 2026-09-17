import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path

import test_dashboard

from wasteland.client import Client, Worker, advertisement, save_config
from wasteland.fair import (
    Index,
    digest,
    document,
    harvest,
    validate,
)
from wasteland.fair_probe import probe
from wasteland.residents import handle

ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads((ROOT / 'examples/fair/ubar.jsonld').read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.index = Index(Path(self.tmp.name) / 'fair.sqlite')

    def tearDown(self):
        self.tmp.cleanup()

    def test_provider_scope_context_and_secret_fields(self):
        self.assertEqual(len(validate(self.doc, 'ubar')), 3)
        for mutate in (
            lambda d: d.update({'@context': 'https://attacker.invalid/context'}),
            lambda d: d['@graph'][0].update(publisher='urn:wasteland:town:yamatai'),
            lambda d: d['@graph'][0].update(token='secret'),
            lambda d: d['@graph'][0]['access'].update(town='yamatai'),
            lambda d: d['@graph'][0].update(license='javascript:alert(1)'),
        ):
            invalid = copy.deepcopy(self.doc)
            mutate(invalid)
            with self.assertRaises(ValueError):
                validate(invalid, 'ubar')

    def test_search_structural_checks_and_honest_gaps(self):
        self.doc['@graph'][0].pop('license', None)
        self.index.ingest('ubar', self.doc)
        self.assertEqual(len(self.index.search('HPO')), 1)
        self.assertEqual(len(self.index.search(semantic_type='http://semanticscience.org/resource/SIO_000089')), 1)
        item = self.index.search('HPO')[0]
        self.assertEqual(item['demonstrated'], [])
        self.assertIn('Explicit reuse license', [c['check'] for c in item['checked']['checks'] if c['status'] == 'missing'])
        self.assertIn('Not scientific validation', item['checked']['scope'])

    def test_offline_withdrawn_and_version_history(self):
        self.index.ingest('ubar', self.doc)
        rid = self.doc['@graph'][0]['@id']
        self.index.failure('ubar', 'offline')
        self.assertEqual(self.index.record(rid)['metadata_contact']['error'], 'offline')
        changed = copy.deepcopy(self.doc)
        changed['@graph'][0]['version'] = 'new-version'
        self.index.ingest('ubar', changed)
        self.assertEqual(len(self.index.revisions(rid)), 2)
        self.index.ingest('ubar', document([]))
        self.assertEqual(self.index.record(rid)['publication'], 'withdrawn')
        self.assertEqual(len(self.index.revisions(rid)), 2)

    def test_rejected_import_does_not_withdraw_previous_records(self):
        self.index.ingest('ubar', self.doc)
        with self.assertRaises(ValueError):
            self.index.ingest('ubar', document([{}]))
        self.assertTrue(all(r['publication'] == 'listed' for r in self.index.search()))

    def test_evidence_is_version_bound_and_does_not_grant_access(self):
        self.index.ingest('ubar', self.doc)
        record = self.doc['@graph'][0]
        evidence = {'record_digest': digest(record), 'summary': 'test observation'}
        self.index.evidence(record['@id'], evidence)
        self.assertEqual(len(self.index.record(record['@id'])['demonstrated']), 1)
        self.doc['@graph'][0]['version'] = 'changed'
        self.index.ingest('ubar', self.doc)
        self.assertEqual(self.index.record(record['@id'])['demonstrated'], [])
        with self.assertRaises(ValueError):
            self.index.evidence(record['@id'], evidence)

    def test_probe_requires_declared_checkpoint_and_records_actual_process(self):
        self.index.ingest('ubar', self.doc)
        record = self.doc['@graph'][0]
        checkpoint = record['version'].removeprefix('sha256:')
        class Responder:
            name = 'observer'
            model = checkpoint
            def ask(self, *args, **kwargs):
                return 'request-1'
            def wait(self, *args, **kwargs):
                return [{'from': 'ubar', 'in_reply_to': 'request-1', 'kind': 'answer', 'id': 'reply-1',
                         'body': {'ok': True, 'checkpoint_sha256': self.model,
                                  'results': [{'gene': 'MGI:123', 'score': 0.4}]}}]
        client = Responder()
        client.model = 'wrong-checkpoint'
        with self.assertRaisesRegex(ValueError, 'checkpoint differs'):
            probe(client, self.index, record['@id'])
        self.assertEqual(self.index.record(record['@id'])['demonstrated'], [])
        client.model = checkpoint
        evidence = probe(client, self.index, record['@id'])
        self.assertIn('http://semanticscience.org/resource/SIO_000230', evidence['run'])
        self.assertEqual(len(self.index.record(record['@id'])['demonstrated']), 1)

    def test_compute_is_never_invoked_by_probe(self):
        doc = json.loads((ROOT / 'examples/fair/yamatai.jsonld').read_text())
        self.index.ingest('yamatai', doc)
        class NoCalls:
            def ask(self, *args, **kwargs):
                raise AssertionError('must not submit compute')
        with self.assertRaisesRegex(ValueError, 'No safe built-in probe'):
            probe(NoCalls(), self.index, doc['@graph'][0]['@id'])


class FederationFairTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_dashboard.DashboardTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.index = Index(self.root / 'index.sqlite')
        doc = json.loads((ROOT / 'examples/fair/ubar.jsonld').read_text())
        for r in doc['@graph']:
            r['@id'] = r['@id'].replace(':ubar:', ':bravo:')
            r['publisher'] = 'urn:wasteland:town:bravo'
            r['access']['town'] = 'bravo'
        self.doc = doc
        path = self.root / 'public.jsonld'
        path.write_text(json.dumps(doc))
        cfg = Client(self.root / 'bravo').config
        cfg['fair_catalogue'] = str(path)
        save_config(self.root / 'bravo', cfg)
        Client(self.root / 'bravo').call('/v1/heartbeat', advertisement(cfg))
        self.stop = threading.Event()
        def run():
            worker = Worker(self.root / 'bravo', handle)
            try:
                worker.run(interval=.02, stop=self.stop)
            finally:
                worker.db.close()
        self.thread = threading.Thread(target=run)
        self.thread.start()

    def tearDown(self):
        self.stop.set()
        self.thread.join(5)
        self.fixture.tearDown()

    def test_authenticated_paginated_harvest_and_public_metadata(self):
        outcomes = harvest(Client(self.root / 'alpha'), self.index, timeout=5)
        self.assertEqual(outcomes, [{'town': 'bravo', 'records': 3, 'ok': True}])
        self.assertEqual(len(self.index.search()), 3)
        self.assertNotIn(Client(self.root / 'bravo').config['token'], json.dumps(self.index.search()))

    def test_tampered_revision_keeps_previous_catalogue(self):
        self.index.ingest('bravo', self.doc)
        class Fake:
            name = 'alpha'
            def call(self, route, *args):
                if 'well-known' in route:
                    return {'towns': [{'name': 'bravo', 'capabilities': ['fair-catalogue']}]}
                return {}
            def ask(self, *args, **kwargs):
                return 'mid'
            def wait(inner, *args, **kwargs):
                return [{'from': 'bravo', 'in_reply_to': 'mid', 'kind': 'answer',
                         'id': 'rid', 'body': {'ok': True, 'catalogue': self.doc, 'revision': 'bad', 'next_offset': None}}]
        result = harvest(Fake(), self.index)
        self.assertFalse(result[0]['ok'])
        self.assertEqual(len(self.index.search()), 3)
