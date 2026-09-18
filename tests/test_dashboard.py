import contextlib
import io
import json
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from wasteland.client import Client, Worker, join, save_config
from wasteland.dashboard import Dashboard, handler
from wasteland.hub import Store
from wasteland.hub import handler as hub_handler
from wasteland.onboarding import configure


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'hub.sqlite')
        invite = secrets.token_urlsafe(32)
        self.invite = invite
        self.hub = ThreadingHTTPServer(('127.0.0.1', 0), hub_handler(self.store, invite, 'http://127.0.0.1'))
        self.ht = threading.Thread(target=self.hub.serve_forever, daemon=True)
        self.ht.start()
        hub = f'http://127.0.0.1:{self.hub.server_port}'
        for town in ('alpha', 'bravo'):
            cfg = join(self.root / town, hub, town, invite)
            with patch('builtins.input', return_value=''), contextlib.redirect_stdout(io.StringIO()):
                cfg = configure(cfg)
            save_config(self.root / town, cfg)
        self.state = Dashboard(self.root / 'alpha')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.state))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.state.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.hub.shutdown()
        self.hub.server_close()
        self.ht.join()
        self.store.db.close()
        self.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers or {'Content-Type': 'application/json', 'X-Town-Token': self.state.token})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def test_directory_and_secret_isolation(self):
        snapshot = self.call('/api/state')
        self.assertEqual({t['name'] for t in snapshot['towns']}, {'alpha', 'bravo'})
        self.assertNotIn(Client(self.root / 'alpha').config['token'], json.dumps(snapshot))
        with urllib.request.urlopen(self.url) as response:
            self.assertIn(b'Read what is happening', response.read())
        with urllib.request.urlopen(self.url + '/operations') as response:
            self.assertIn(b'Town operations', response.read())

    def test_csrf_and_rebinding_rejected(self):
        for headers in ({'Content-Type': 'application/json'},
                        {'Content-Type': 'application/json', 'X-Town-Token': self.state.token, 'Origin': 'https://evil.example'},
                        {'Host': 'evil.example'}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.call('/api/start', {}, headers)
            self.assertEqual(caught.exception.code, 403)

    def test_send_guide_reply_and_persistent_history(self):
        result = self.call('/api/send', {'to': 'bravo', 'resident': 'guide', 'operation': 'message', 'text': 'Hello'})
        peer = Worker(self.root / 'bravo')
        try:
            peer.tick()
        finally:
            peer.db.close()
        snapshot = self.call('/api/state')
        self.assertEqual(snapshot['outgoing'][0]['id'], result['id'])
        self.assertEqual(snapshot['outgoing'][0]['result']['replies'][0]['body']['resident'], 'guide')
        restarted = Dashboard(self.root / 'alpha')
        self.assertIsNotNone(restarted.snapshot()['outgoing'][0]['result'])

    def test_trust_and_resource_controls_enforced_by_worker(self):
        trust = {'trusted': ['bravo'], 'blocked': [], 'resources': 'trusted', 'models': 'trusted'}
        self.call('/api/trust', {'trust': trust})
        resource = self.root / 'results.tsv'
        resource.write_text('a\tb\n')
        self.call('/api/publish', {'path': str(resource)})
        cfg = Client(self.root / 'alpha').config
        self.assertEqual(cfg['trust'], trust)
        self.assertEqual(len(cfg['resources']), 1)
        self.call('/api/unpublish', {'id': cfg['resources'][0]['id']})
        self.assertEqual(Client(self.root / 'alpha').config['resources'], [])
        with self.assertRaises(urllib.error.HTTPError):
            self.call('/api/publish', {'path': str(self.root / 'alpha/town.json')})

    def test_worker_start_stop(self):
        self.assertTrue(self.call('/api/start', {})['running'])
        self.assertFalse(self.call('/api/stop', {})['running'])
