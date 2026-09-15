import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from wasteland.resources import download


class DownloadTests(unittest.TestCase):
    def test_verified_chunks_no_overwrite_and_failed_transfer_cleanup(self):
        data = b'published data'*3000
        digest = 'sha256:' + hashlib.sha256(data).hexdigest()
        class Client:
            bad = False
            def ask(self, town, body):
                self.body = body
                return 'id'
            def wait(self, mid, timeout):
                start = self.body['offset']
                chunk = data[start:start+24000]
                return [{'body': {'ok': True, 'id': 'resource', 'offset': start,
                         'next_offset': start+len(chunk), 'bytes': len(data), 'sha256': digest,
                         'data': base64.b64encode(b'bad' if self.bad else chunk).decode(),
                         'eof': start+len(chunk)==len(data)}}]
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'result.txt'
            client = Client()
            result = download(client,'ubar','resource',out)
            self.assertEqual(result['sha256'],digest)
            self.assertEqual(out.read_bytes(),data)
            with self.assertRaises(ValueError):
                download(client,'ubar','resource',out)
            out.unlink()
            client.bad = True
            with self.assertRaises(ValueError):
                download(client,'ubar','resource',out)
            self.assertEqual(list(Path(folder).iterdir()),[])
