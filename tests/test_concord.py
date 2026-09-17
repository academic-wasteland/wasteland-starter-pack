import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from wasteland import concord
from wasteland.concord_city import answer, handler


def always_accept(case):
    return True


def explode(case):
    raise ValueError('must not count as a valid rejection')


class ConcordTests(unittest.TestCase):
    def run_suite(self,slug='signed-status-receiver',adapter='wasteland.concord_checks:starter_status'):
        return concord.execute(slug,adapter,implementation='test implementation',version='test-version',observer='test observer')

    def test_reference_profiles_and_failed_adapter(self):
        for slug, adapter, count in [('signed-status-receiver','starter_status',17),('holder-key-binding','holder_key',9)]:
            report=self.run_suite(slug,'wasteland.concord_checks:'+adapter)
            self.assertEqual(concord.summary(report),{'passed':count,'total':count,'outcome':'pass'})
            concord.validate(report)
        bad=self.run_suite(adapter=__name__+':always_accept')
        self.assertEqual(concord.summary(bad)['passed'],1)
        self.assertEqual(concord.summary(bad)['outcome'],'fail')
        broken=self.run_suite(adapter=__name__+':explode')
        self.assertTrue(all(r['result']=='error' for r in broken['results']))

    def test_report_tamper_missing_checks_and_version_binding(self):
        report=self.run_suite()
        broken=copy.deepcopy(report);broken['results'][0]['result']='fail'
        with self.assertRaisesRegex(ValueError,'digest'):
            concord.validate(broken)
        for change in ('checks','profile','provenance'):
            broken=copy.deepcopy(report)
            if change=='checks':broken['results'].pop()
            elif change=='profile':broken['profile_digest']='sha256:wrong'
            else:broken.pop('observer')
            broken['id']=concord.digest({k:v for k,v in broken.items() if k!='id'})
            with self.assertRaises(ValueError):concord.validate(broken)

    def test_http_and_relay_read_only_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=self.run_suite();path=concord.save_report(tmp,report)
            self.assertEqual(path,concord.save_report(tmp,report))
            self.assertEqual(len(concord.reports(tmp)),1)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(tmp))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base+'/api/catalogue') as response:
                    body=json.load(response)
                self.assertEqual(len(body['profiles']),2)
                self.assertEqual(body['reports'][0]['summary']['outcome'],'pass')
                with urllib.request.urlopen(base+'/profiles/signed-status-receiver/1.0.0.json') as response:
                    self.assertEqual(json.load(response)['version'],'1.0.0')
                for path in ('/profiles/../../pyproject.toml','/profiles/signed-status-receiver/2.0.0','/api/report?id=missing'):
                    with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+path)
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(urllib.request.Request(base+'/api/run',data=b'{}'))
                response=answer({'body':{'operation':'standard-profile','id':'signed-status-receiver'}},{'concord_reports':tmp})
                self.assertTrue(response['ok'])
                self.assertEqual(response['digest'],report['profile_digest'])
                self.assertFalse(answer({'body':{'operation':'execute','adapter':'evil'}},{'concord_reports':tmp})['ok'])
                self.assertEqual(answer({'body':{'operation':'conformance-report','id':report['id']}},{'concord_reports':tmp})['report']['id'],report['id'])
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_cli_failed_suite_exits_nonzero(self):
        import os
        import subprocess
        import sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'bad_adapter.py').write_text('def check(case): return True\n')
            env={**os.environ,'PYTHONPATH':tmp+os.pathsep+str(Path(__file__).resolve().parents[1])}
            result=subprocess.run([sys.executable,'-m','wasteland','concord-check','--profile','signed-status-receiver',
                                   '--adapter','bad_adapter:check','--implementation','deliberately unsafe test fixture',
                                   '--version','test','--observer','test','--out',tmp],env=env,capture_output=True,text=True,check=False)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['outcome'],'fail')

    def test_profile_release_manifest_detects_changes(self):
        import shutil
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'profiles'
            shutil.copytree(concord.ROOT,root)
            path=next(root.glob('*.json'))
            path.write_text(path.read_text()+' ')
            with patch.object(concord,'ROOT',root), self.assertRaisesRegex(ValueError,'changed'):
                concord.profiles()
