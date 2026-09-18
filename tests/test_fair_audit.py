import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from wasteland.fair import Index, document
from wasteland.fair_audit import Auditor
from wasteland.fair_city import answer


class Client:
    name = 'fairhaven'
    def __init__(self, directory):
        self.directory = directory
        self.calls, self.sent, self.requests = [], [], {}
        self.fail_send = False
        self.bad_sender = False
        self.towns = [{'name': n, 'capabilities': ['describe', 'echo', 'compute', 'credential-apply', 'resident:liaison']} for n in ('bravo', 'alpha')]
    def call(self, path):
        return {'towns': self.towns}
    def ask(self, town, operation, body):
        mid = str(len(self.calls)); self.calls.append((town, operation)); self.requests[mid] = (town, operation, body)
        return mid
    def wait(self, mid, timeout):
        town, op, body = self.requests[mid]
        output = {'ok': True, 'text': 'available'}
        if op == 'resource':
            data = b'gene\nFBN1\n'
            output = {'ok':True,'id':body['id'],'offset':0,'bytes':len(data),'data':base64.b64encode(data).decode(),
                      'next_offset':len(data),'eof':True,'sha256':'sha256:'+hashlib.sha256(data).hexdigest()}
        return [{'id':'reply-'+mid,'from':'imposter' if self.bad_sender else town,'in_reply_to':mid,'kind':'answer','body':output}]
    def send(self, message):
        self.sent.append(message)
        if self.fail_send:
            raise RuntimeError('Simulated lost receipt')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.client = Client(self.root)
        self.index = Index(self.root/'index.sqlite')
        self.time = 10000
        self.auditor = Auditor(self.client, self.index, clock=lambda:self.time)

    def test_sequential_hourly_persistent_and_safe(self):
        self.auditor.tick()
        self.assertEqual(self.client.calls, [('alpha','describe'),('alpha','echo'),('bravo','describe'),('bravo','echo')])
        self.assertEqual(len(self.client.sent), 2)
        for notice in self.client.sent:
            self.assertEqual(notice['body']['resident'], 'liaison')
            self.assertNotIn('visibility', notice)
            self.assertIn('not tested', notice['body']['text'])
        self.time += 3599
        restarted = Auditor(self.client,self.index,clock=lambda:self.time)
        restarted.tick(); self.assertEqual(len(self.client.sent),2)
        self.time += 1
        restarted.tick(); self.assertEqual(len(self.client.sent),4)
        self.assertEqual(self.auditor.latest('alpha')['counts'], {'working':2,'failed':0,'not tested':2})

    def test_notification_retry_reuses_id_without_repeating_probes(self):
        self.client.fail_send = True
        self.auditor.tick(); original = list(self.client.calls); ids = [m['id'] for m in self.client.sent]
        self.client.fail_send = False
        Auditor(self.client,self.index,clock=lambda:self.time).tick()
        self.assertEqual(self.client.calls, original)
        self.assertEqual([m['id'] for m in self.client.sent[2:]], ids)

    def test_failed_or_budget_exhausted_is_not_working(self):
        self.client.bad_sender = True
        report = self.auditor.audit(self.client.towns[0])
        self.assertEqual(report['counts']['working'], 0)
        self.assertEqual(report['counts']['failed'],2)
        deadline = self.auditor.monotonic()-1
        self.assertEqual(self.auditor.check('alpha','echo',{},deadline)[0],'not tested')

    def test_working_record_gets_fair_actions_and_no_returned_data(self):
        source = json.loads((Path(__file__).parents[1]/'examples/fair/ubar.jsonld').read_text())['@graph'][0]
        record = json.loads(json.dumps(source).replace('ubar','alpha'))
        record['access']['operation'] = 'resource'
        record['example'] = {'operation':'resource','id':'small-example'}
        record.pop('license',None)
        self.index.ingest('alpha',document([record]))
        report = self.auditor.audit({'name':'alpha','capabilities':['describe','resource']})
        item = next(c for c in report['checks'] if 'id' in c)
        self.assertEqual(item['status'],'working')
        self.assertTrue(any('license' in s for s in item['suggestions']))
        self.assertNotIn('FBN1',json.dumps(report))
        self.assertNotIn('FBN1',json.dumps(self.auditor.status()))

    def test_resource_digest_failure_and_large_resource_are_not_passes(self):
        original = self.client.wait
        def wrong(mid, timeout):
            result = original(mid,timeout); result[0]['body']['sha256']='sha256:bad'; return result
        self.client.wait = wrong
        self.assertEqual(self.auditor.check('alpha','resource',{'id':'x'},self.auditor.monotonic()+5)[0],'failed')
        def large(mid, timeout):
            result = original(mid,timeout); result[0]['body'].update(eof=False,bytes=50000); return result
        self.client.wait = large
        self.assertEqual(self.auditor.check('alpha','resource',{'id':'x'},self.auditor.monotonic()+5)[0],'not tested')

    def test_report_only_for_authenticated_requesting_town(self):
        from unittest.mock import patch
        self.auditor.tick()
        config={'fair_index':str(self.index.path),'fair_state':str(self.root)}
        with patch('wasteland.fair_city.Client', return_value=self.client):
            result=answer({'from':'bravo','body':{'operation':'fair-audit','town':'alpha'}},config)
            self.assertEqual(result['report']['town'],'bravo')
            self.assertEqual(len(result['report']['checks']),1)
            self.assertEqual(result['report']['next_offset'],1)
            self.assertIsNone(answer({'from':'unknown','body':{'operation':'fair-audit'}},config)['report'])


class RelayAuditTests(unittest.TestCase):
    def test_real_relay_contact_report_delivery_and_private_activity(self):
        from contextlib import closing
        import threading
        import test_dashboard
        from wasteland.client import Client as RealClient, Worker
        f = test_dashboard.DashboardTests(); f.setUp()
        stop = threading.Event()
        def work():
            worker = Worker(f.root/'bravo')
            try:
                worker.run(interval=.02, stop=stop)
            finally:
                worker.db.close()
        thread = threading.Thread(target=work)
        thread.start()
        try:
            client = RealClient(f.root/'alpha')
            audit = Auditor(client, Index(f.root/'audit-index.sqlite'), timeout=5)
            audit.tick()
            report = audit.latest('bravo')
            self.assertGreater(report['counts']['working'],0)
            with closing(audit.db()) as db:
                row = db.execute('SELECT notice,sent FROM reports WHERE town="bravo"').fetchone()
            notice = json.loads(row['notice'])
            self.assertEqual(row['sent'],1)
            received = RealClient(f.root/'bravo').call('/v1/messages/'+notice['id'])['message']
            self.assertIn('FAIRhaven hourly service report',received['body']['text'])
            self.assertTrue(all('body' not in e for e in client.call('/v1/activity')['events']))
        finally:
            stop.set(); thread.join(5); f.tearDown()
