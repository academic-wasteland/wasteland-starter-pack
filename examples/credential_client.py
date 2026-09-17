"""Apply for/fetch a manually reviewed holder credential over the relay.

Install: pip install '.[credentials]'. The private key stays in --key (0600).
Application JSON has credential_type, issuer (slug), subject_fields and purpose.
"""
import argparse
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from wasteland.client import Client
from wasteland.credentials import holder_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('.town'))
    parser.add_argument('--authority', default='camelot')
    parser.add_argument('--holder', required=True)
    parser.add_argument('--key', type=Path, required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('apply').add_argument('application', type=Path)
    commands.add_parser('fetch').add_argument('application')
    args = parser.parse_args()
    if not args.key.exists():
        if args.action != 'apply':
            parser.error('fetch requires the existing application key')
        key = Ed25519PrivateKey.generate()
        args.key.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    else:
        if args.key.stat().st_mode & 0o077:
            parser.error('private key must have mode 0600')
        key = Ed25519PrivateKey.from_private_bytes(args.key.read_bytes())
    application = json.loads(args.application.read_text()) if args.action == 'apply' else args.application
    print(json.dumps(holder_request(Client(args.state), args.authority, key, args.holder,
                                    action=args.action, application=application), indent=2))


if __name__ == '__main__':
    main()
