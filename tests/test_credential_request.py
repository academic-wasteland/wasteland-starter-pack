import unittest
import test_dashboard
from wasteland.client import Client

class CredentialRequestTests(unittest.TestCase):
    def setUp(self):
        self.f = test_dashboard.DashboardTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def test_ask_keeps_operation_with_structured_body(self):
        client=Client(self.f.root/'bravo')
        mid=client.ask('alpha', operation='credential-challenge', body={'request':{'holder':'participant'}})
        wire=client.call('/v1/messages/'+mid)['message']
        self.assertEqual(wire['body']['operation'],'credential-challenge')
        self.assertEqual(wire['body']['request'],{'holder':'participant'})
