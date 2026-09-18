"""Worker startup is observable even with an empty inbox; no model is required."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wasteland.client import Worker, RemoteError, save_config
from wasteland.onboarding import configure
from wasteland.protocol import envelope


class StatusTests(unittest.TestCase):
    def exercise(self, responses):
        output = io.StringIO()
        clock = [100.0]
        sent = []
        remaining = list(responses)
        class Stop:
            def is_set(self): return not remaining
            def wait(self, interval): clock[0] += 61
        def request(base, path, **kw):
            if path == '/v1/inbox':
                value = remaining.pop(0)
                if isinstance(value, Exception): raise value
                return {'messages': value}
            if path == '/v1/messages': sent.append(kw['data'])
            return {'ok': True}
        with tempfile.TemporaryDirectory() as tmp:
            with patch('builtins.input', return_value=''), contextlib.redirect_stdout(io.StringIO()):
                config = configure({'name':'jo_one', 'display':'Jo One', 'hub':'https://example.org', 'token':'private'})
            save_config(Path(tmp), config)
            worker = Worker(Path(tmp))
            try:
                with patch('wasteland.client.request', side_effect=request), patch('wasteland.client.time.monotonic', side_effect=lambda: clock[0]), contextlib.redirect_stdout(output):
                    worker.run(interval=0, stop=Stop())
            finally: worker.db.close()
        return output.getvalue(), sent

    def test_idle_worker_reports_connection_and_periodic_wait(self):
        output, sent = self.exercise([[], []])
        self.assertIn('starting worker', output)
        self.assertIn('connected; listening', output)
        self.assertIn('waiting for messages', output)
        self.assertEqual(sent, [])

    def test_incoming_contact_gets_real_guide_reply_without_model(self):
        request = envelope('ubar', 'jo_one', 'Hello Jo One; please acknowledge this test.', 'message')
        output, sent = self.exercise([[], [request]])
        self.assertIn('processed 1 message', output)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['in_reply_to'], request['id'])
        self.assertTrue(sent[0]['body']['ok'])
        self.assertTrue(sent[0]['body']['text'])

    def test_unreachable_relay_not_reported_as_connected(self):
        output, _ = self.exercise([RemoteError('offline')])
        self.assertNotIn('connected;', output)
        self.assertIn('offline; retrying', output)
