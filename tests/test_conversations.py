import json
import tempfile
import unittest
from pathlib import Path

from wasteland.conversations import CONTEXT, Store, context
from wasteland.protocol import envelope
import test_dashboard as fixture


class ConversationStoreTests(unittest.TestCase):
    def test_people_stable_ids_memberships_and_causal_reply_validation(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root) / 'people.sqlite')
            a = store.save_person({'display': 'Robert', 'memberships': [{'town': 'ubar', 'role': 'owner'}, {'town': 'yamatai', 'role': 'owner'}]}, ['ubar', 'yamatai'])
            b = store.save_person({'display': 'Another visitor'}, ['ubar', 'yamatai'])
            self.assertNotEqual(a['id'], b['id'])
            renamed = store.save_person(dict(a, display='Robert Hoehndorf'), ['ubar', 'yamatai'])
            self.assertEqual(a['id'], renamed['id'])
            t = store.create(a['id'], 'yamatai', 'ubar', 'contact', 'Help investigate')
            q = envelope('yamatai', 'ubar', body={CONTEXT: store.context(t), 'text': 'Help'})
            store.add(t['id'], event_id=q['id'], sender='Robert via yamatai', recipient='ubar/contact', text='Help', state='sent')
            fake = envelope('intruder', 'yamatai', kind='answer', parent=q['id'], body={'text': 'done'})
            self.assertFalse(store.receive(t['id'], fake))
            reply = envelope('ubar', 'yamatai', kind='notice', parent=q['id'], body={'state': 'delivered-to-resident', 'text': 'Delivered'})
            self.assertTrue(store.receive(t['id'], reply))
            self.assertEqual(store.events(t['id'])[-1]['state'], 'delivered-to-resident')
            restarted = Store(Path(root) / 'people.sqlite')
            self.assertEqual(len(restarted.people()), 2)
            self.assertEqual(restarted.get(t['id'])['person_id'], a['id'])
            with self.assertRaises(ValueError):
                store.save_person({'display': 'X', 'memberships': [{'town': 'remote', 'role': 'owner'}]}, ['ubar'])
            invalid = store.context(t)
            invalid['actor']['role'] = 'admin'
            with self.assertRaises(ValueError):
                context(invalid)


class ConversationRelayTests(unittest.TestCase):
    setUp = fixture.DashboardTests.setUp
    tearDown = fixture.DashboardTests.tearDown
    call = fixture.DashboardTests.call
    # Reuse isolated real relay + dashboard setup, not a production town.
    def test_named_person_conversation_actual_relay_and_restart(self):
        from wasteland.client import Client, Worker, advertisement
        from wasteland.dashboard import Dashboard
        peer = Client(self.root / 'bravo')
        peer.call('/v1/heartbeat', advertisement(peer.config))
        person = self.call('/api/conversations/person', {'display': 'Ada Example', 'memberships': [{'town': 'alpha', 'role': 'owner'}]})['person']
        response = self.call('/api/conversations/send', {'person_id': person['id'], 'via': 'alpha', 'to': 'bravo',
                                                          'resident': 'guide', 'text': 'What can you help with?'})
        cid = response['conversation']
        from wasteland.residents import handle
        seen = []
        def checked_handler(message, config):
            self.assertNotIn(CONTEXT, message['body'])
            self.assertEqual(message[CONTEXT]['actor']['id'], person['id'])
            seen.append(message)
            return handle(message, config)
        worker = Worker(self.root / 'bravo', checked_handler)
        try:
            worker.tick()
        finally:
            worker.db.close()
        self.assertEqual(len(seen), 1)
        result = self.call('/api/conversations?id=' + cid)
        self.assertEqual(result['conversation']['person']['display'], 'Ada Example')
        reply = next(e for e in result['events'] if e['state'] == 'replied')
        self.assertEqual(reply['payload'][CONTEXT]['actor']['id'], person['id'])
        self.assertEqual(reply['payload'][CONTEXT]['id'], cid)
        self.assertNotIn(Client(self.root / 'alpha').config['token'], json.dumps(result))
        restarted = Dashboard(self.root / 'alpha')
        self.assertEqual(restarted.conversations.snapshot(cid)['conversation']['id'], cid)
        other = self.call('/api/conversations/person', {'display': 'Other visitor'})['person']
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError):
            self.call('/api/conversations/send', {'conversation': cid, 'person_id': other['id'], 'text': 'Impersonate'})
