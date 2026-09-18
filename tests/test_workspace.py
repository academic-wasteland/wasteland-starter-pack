"""Real dashboard endpoints must expose content without granting new access."""
import json
import unittest
import urllib.error
import urllib.request

import test_dashboard
from wasteland.client import Client, Worker
from wasteland.protocol import envelope
from wasteland.workspace import envelope as project_envelope, project


class ProjectionTests(unittest.TestCase):
    def test_full_content_search_explicit_links_and_no_payload_in_list(self):
        body = {'text': 'x' * 9000 + 'unique end marker', 'results': [{'gene': 'FBN1', 'score': 0.97}]}
        first = envelope('alpha', 'bravo', body=body)
        reply = envelope('bravo', 'alpha', body={'text': 'Actual answer'})
        reply['in_reply_to'] = first['id']
        unrelated = envelope('alpha', 'bravo', body={'text': 'Different task'})
        messages = [project_envelope(m) for m in (first, reply, unrelated)]
        view = project(messages, selected=first['id'], search='unique end marker')
        self.assertEqual(len(view['messages']), 1)
        self.assertNotIn('payload', view['messages'][0])
        self.assertEqual(view['detail']['message']['text'], body['text'])
        self.assertEqual(view['detail']['message']['payload'], body)
        self.assertEqual([m['id'] for m in view['detail']['related']], [reply['id']])
        self.assertEqual(project(messages, selected='missing')['detail'], None)

    def test_named_copy_does_not_hide_wire_payload_or_status(self):
        wire = project_envelope(envelope('alpha', 'bravo', body={'text': 'Actual wire text', 'result': [1, 2]}), status='sent')
        named = dict(wire, source='conversation', sender='Robert via alpha', text='A summary',
                     payload={'summary': True}, state='queued', conversation='conversation-1')
        result = project([wire, named], selected=wire['id'])
        self.assertEqual(len(result['messages']), 1)
        message = result['detail']['message']
        self.assertEqual(message['sender'], 'Robert via alpha')
        self.assertEqual(message['text'], 'Actual wire text')
        self.assertEqual(message['payload']['result'], [1, 2])
        self.assertEqual(message['state'], 'sent')


class WorkspaceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_dashboard.DashboardTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_worker_history_remains_readable_after_acknowledgement(self):
        f = self.fixture
        client = Client(f.root / 'bravo')
        text = 'Read this full message: ' + 'phenotype data ' * 350
        mid = client.ask('alpha', operation='message', text=text, body={'resident': 'guide'})
        worker = Worker(f.root / 'alpha')
        try:
            worker.tick()
        finally:
            worker.db.close()
        self.assertEqual(Client(f.root / 'alpha').call('/v1/inbox')['messages'], [])
        view = f.call('/api/workspace?id=' + mid)
        self.assertEqual(view['detail']['message']['text'], text)
        self.assertTrue(view['detail']['related'])
        self.assertEqual(view['access']['managed'], ['alpha'])
        self.assertNotIn(Client(f.root / 'alpha').config['token'], json.dumps(view))
        searched = f.call('/api/workspace?q=phenotype')
        self.assertIn(mid, [m['id'] for m in searched['messages']])
        with self.assertRaises(urllib.error.HTTPError) as error:
            f.call('/api/workspace', headers={'Host': 'evil.example'})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_named_conversations_appear_without_changing_person_identity(self):
        f = self.fixture
        store = f.state.conversations.store
        person = store.save_person({'display': 'Alex', 'memberships': []}, ['alpha'])
        thread = store.create(person['id'], 'alpha', 'bravo', 'guide', 'Question')
        store.add(thread['id'], sender='Alex via alpha', recipient='bravo/guide', text='Please investigate', state='queued', payload={'phenotypes': ['Ectopia lentis (HP:0001083)']})
        view = f.call('/api/workspace')
        message = next(m for m in view['messages'] if m['conversation'] == thread['id'])
        detail = f.call('/api/workspace?id=' + message['id'])['detail']['message']
        self.assertEqual(detail['sender'], 'Alex via alpha')
        self.assertEqual(detail['payload']['phenotypes'], ['Ectopia lentis (HP:0001083)'])
