"""Fetch a declared town resource over the existing authenticated mailbox."""
import base64
import hashlib
import os
import tempfile
from pathlib import Path

from .client import RemoteError


def download(client, town, identifier, output, timeout=120):
    output = Path(output)
    if output.exists():
        raise ValueError('destination already exists')
    offset, digest, total = 0, None, None
    h = hashlib.sha256()
    fd, temporary = tempfile.mkstemp(prefix='.wasteland-download-', dir=output.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            while True:
                mid = client.ask(town, body={'operation': 'resource', 'id': identifier,
                                            'offset': offset, 'sha256': digest})
                body = client.wait(mid, timeout)[0]['body']
                if not body.get('ok'):
                    raise RemoteError(body.get('error', 'resource request failed'))
                if body.get('id') != identifier or body.get('offset') != offset:
                    raise ValueError('resource response does not match request')
                if digest is None:
                    digest, total = body['sha256'], body['bytes']
                    if type(total) is not int or not 0 <= total <= 50*1024*1024:
                        raise ValueError('invalid resource size')
                if body['sha256'] != digest or body['bytes'] != total:
                    raise ValueError('resource changed during download')
                chunk = base64.b64decode(body['data'], validate=True)
                if len(chunk) > 24000 or body['next_offset'] != offset + len(chunk) or offset + len(chunk) > total:
                    raise ValueError('invalid resource chunk')
                stream.write(chunk)
                h.update(chunk)
                offset += len(chunk)
                if body['eof']:
                    if offset != total or 'sha256:' + h.hexdigest() != digest:
                        raise ValueError('resource digest mismatch')
                    break
                if not chunk:
                    raise ValueError('resource download made no progress')
        os.link(temporary, output)  # atomic no-clobber publication on the same filesystem
        return {'path': str(output), 'bytes': total, 'sha256': digest}
    finally:
        Path(temporary).unlink(missing_ok=True)
