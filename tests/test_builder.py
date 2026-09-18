import json
import unittest
from unittest.mock import patch

import test_dashboard
from wasteland.builder import snapshot
from wasteland.client import Client, Worker, save_config
from wasteland.dashboard import Dashboard
from wasteland.residents import handle


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.f = test_dashboard.DashboardTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.state = self.f.state

    def edit(self, action, **body):
        return self.state.action('builder/' + action, dict(body, revision=snapshot(self.state)['revision']))

    def test_agents_preserve_identity_and_custom_fields_and_guide(self):
        config = self.state.config()
        config['extension'] = {'keep': True}
        save_config(self.state.directory, config)
        self.edit('agent', name='researcher', role='Phenotype researcher', mode='model', interests=['HPO'], editing=False,
                  model={'url': 'http://localhost:11434/v1', 'name': 'qwen', 'key_env': 'LOCAL_KEY'})
        self.edit('agent', name='researcher', role='Updated role', mode='guide', interests=[], editing=True)
        after = self.state.config()
        self.assertEqual(after['token'], config['token'])
        self.assertEqual(after['extension'], config['extension'])
        self.assertEqual(after['residents'][1]['model']['key_env'], 'LOCAL_KEY')
        with self.assertRaisesRegex(ValueError, 'guide'):
            self.edit('remove-agent', name='guide')
        with self.assertRaisesRegex(ValueError, 'environment variable'):
            self.edit('agent', name='bad', role='Bad', mode='model', model={'url':'http://localhost:1/v1','name':'x','key_env':'sk-not-a-variable'})
        self.edit('remove-agent', name='researcher')
        reply = handle({'from':'outside','body':{'operation':'message','text':'Hello','resident':'guide'}}, self.state.config())
        self.assertTrue(reply['ok'])
        self.assertNotIn(config['token'], json.dumps(snapshot(self.state)))

    def test_resource_metadata_trust_and_unpublish_do_not_delete_file(self):
        path = self.f.root / 'results.tsv'
        path.write_text('gene\nFBN1\n')
        self.edit('resource', path=str(path), name='Candidate genes', description='Synthetic case', license='CC BY 4.0')
        self.edit('trust', trust={'trusted':['bravo'],'blocked':[], 'resources':'trusted','models':'trusted'})
        config = self.state.config()
        self.assertFalse(handle({'from':'outside','body':{'operation':'resources'}},config)['ok'])
        resources = handle({'from':'bravo','body':{'operation':'resources'}},config)['resources']
        self.assertEqual(resources[0]['description'], 'Synthetic case')
        self.assertEqual(resources[0]['license'], 'CC BY 4.0')
        self.edit('remove-resource', id=resources[0]['id'])
        self.assertTrue(path.exists())
        self.assertEqual(self.state.config()['resources'], [])
        with self.assertRaises(ValueError):
            self.edit('resource', path=str(self.state.directory/'town.json'))

    def test_conflicts_custom_runtime_and_invalid_edits_leave_config_untouched(self):
        before = self.state.config()
        for action, body in [('profile', {'revision':'stale'}), ('trust', {'trust':{'trusted':['bravo'],'blocked':['bravo'],'resources':'everyone','models':'trusted'}}), ('agent',{'name':'invalid-agent','role':'x','mode':'guide'})]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.state.action('builder/'+action, {'revision': snapshot(self.state)['revision'], **body})
            self.assertEqual(self.state.config(),before)
        before['handler']='custom:handler';save_config(self.state.directory,before)
        self.assertFalse(snapshot(self.state)['editable'])
        with self.assertRaisesRegex(ValueError,'Custom'):
            self.edit('profile',display='wrong',description='wrong')
        self.assertEqual(self.state.config(),before)

    def test_browser_registration_uses_real_relay_and_rejects_identity_replacement(self):
        state = Dashboard(self.f.root/'newtown')
        self.addCleanup(state.stop)
        self.assertFalse(snapshot(state)['configured'])
        body={'name':'newtown','display':'New Town','hub':Client(self.f.root/'alpha').config['hub'],'invite':self.f.invite}
        state.action('builder/join',body)
        self.assertTrue(snapshot(state)['configured'])
        worker=Worker(state.directory)
        try:
            peer=Client(self.f.root/'bravo')
            mid=peer.ask('newtown',operation='message',text='Hello',body={'resident':'guide'})
            worker.tick()
            self.assertTrue(peer.wait(mid,5)[0]['body']['ok'])
        finally:
            worker.db.close()
        with self.assertRaisesRegex(ValueError,'already'):
            state.action('builder/join',body)
        self.assertNotIn(self.f.invite,json.dumps(state.config()))

    def test_public_activity_never_contains_payloads_or_credentials(self):
        client=Client(self.f.root/'bravo')
        mid=client.ask('alpha',operation='message',text='SECRET PATIENT',body={'private':'VCF CONTENT'})
        view=self.f.call('/api/builder')
        self.assertTrue(view['configured'])
        activity=self.f.store.activity()
        raw=json.dumps(activity)
        for private in ('SECRET PATIENT','VCF CONTENT',mid,client.config['token']):
            self.assertNotIn(private,raw)
        self.assertEqual(set(activity['events'][0]), {'sequence','from','to','received','status'})
        self.assertEqual(activity['events'][0]['status'],'queued')
        Client(self.f.root/'alpha').call('/v1/ack',{'id':mid})
        self.assertEqual(self.f.store.activity()['events'][0]['status'],'collected')
