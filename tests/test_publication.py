import json
import unittest

import test_dashboard
from wasteland.client import Client, Worker, request, RemoteError
from wasteland.protocol import envelope


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.f = test_dashboard.DashboardTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def test_only_explicit_public_body_is_exposed_and_replies_remain_private(self):
        peer = Client(self.f.root/'bravo')
        private = peer.ask('alpha', text='PRIVATE', body={'visibility':'public','nested':{'_visibility':'public'}})
        public = peer.ask('alpha', operation='echo', text='<img src=x onerror=alert(1)>', public=True,
                          body={'data':{'gene':'FBN1'}, '_conversation_private':'ordinary payload'})
        worker = Worker(self.f.root/'alpha')
        try:
            worker.tick()
        finally:
            worker.db.close()
        activity = request(peer.config['hub'], '/v1/activity')
        exposed = [e for e in activity['events'] if 'body' in e]
        self.assertEqual(len(exposed),1)
        self.assertEqual(exposed[0]['body']['data'], {'gene':'FBN1'})
        self.assertNotIn('PRIVATE', json.dumps(activity))
        self.assertNotIn(private, json.dumps(activity))
        self.assertNotIn(public, json.dumps(activity))
        self.assertTrue(peer.wait(public,5)[0]['body'])
        # Attempts to retroactively flip the flag cannot rewrite an accepted envelope.
        message = peer.call('/v1/messages/'+private)['message']
        message['visibility'] = 'public'
        with self.assertRaisesRegex(Exception, 'different contents'):
            peer.send(message)
        self.assertNotIn('PRIVATE',json.dumps(request(peer.config['hub'],'/v1/activity')))

    def test_context_not_published_and_invalid_visibility_rejected(self):
        peer=Client(self.f.root/'bravo')
        for value in (True, 'PUBLIC', 1, None, [], {}):
            msg=envelope('bravo','alpha',text='secret')
            msg['visibility']=value
            with self.subTest(value=value):
                with self.assertRaises(RemoteError) as caught:
                    peer.send(msg)
                self.assertEqual(caught.exception.status, 400)
        msg=envelope('bravo','alpha',body={'text':'Public notice','_conversation':{'id':'PRIVATE-ID'}})
        msg['visibility']='public';peer.send(msg)
        data=request(peer.config['hub'],'/v1/activity')
        self.assertNotIn('PRIVATE-ID',json.dumps(data))
        self.assertEqual(data['events'][0]['body'], {'text':'Public notice'})

