"""Deterministic public conformance vectors; adapters are explicitly local code.

No relay or HTTP request can load or execute an adapter. Fixtures use disposable
keys and fabricated credentials. They never grant real access.
"""
import base64
import copy
from datetime import UTC, datetime, timedelta

from . import credentials


def vectors(slug):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))  # PUBLIC TEST SEED, never an issuer key.
    public = credentials.public_key(key)
    if slug == 'holder-key-binding':
        subjects = {'holder-key': {'holderKey': public}, 'public-key': {'publicKey': public},
                    'matching-aliases': {'holderKey': public, 'publicKey': public},
                    'conflicting-aliases': {'holderKey': public, 'publicKey': credentials.public_key(Ed25519PrivateKey.from_private_bytes(bytes(range(1,33))))},
                    'missing-key': {}, 'wrong-scheme': {'publicKey': public.replace('ed25519:', 'rsa:')},
                    'short-key': {'publicKey': 'ed25519:YQ'}, 'malformed-base64': {'publicKey': 'ed25519:!!!!'}, 'bad-subject': []}
        return {name: {'credential': {'credentialSubject': subject}, 'expected_key': public}
                for name, subject in subjects.items()}
    if slug != 'signed-status-receiver':
        raise ValueError('Unknown test suite')
    now = datetime(2026,9,17,12,0,0,tzinfo=UTC)
    credential = {'id':'https://example.org/credentials/test','issuer':'https://example.org/issuers/test',
                  'credentialStatus':{'id':'https://example.org/status/test'}}
    body = {'type':'CredentialStatusStatement','id':credential['id'],'credential':credential['id'],
            'issuer':credential['issuer'],'status_id':credential['credentialStatus']['id'],
            'status':'active','as_of':now.isoformat(),'valid_until':(now+timedelta(seconds=60)).isoformat()}
    changes = {'active':{}, 'revoked':{'status':'revoked'}, 'suspended':{'status':'suspended'}, 'unknown':{'status':'unknown'},
               'unsigned':{}, 'tampered':{}, 'untrusted-key':{}, 'wrong-issuer':{'issuer':'urn:other'},
               'wrong-credential':{'credential':'urn:other'}, 'wrong-status-id':{'status_id':'urn:other'}, 'wrong-request-id':{'id':'urn:other'},
               'stale':{'as_of':(now-timedelta(seconds=61)).isoformat(),'valid_until':(now-timedelta(seconds=1)).isoformat()},
               'expired':{'as_of':(now-timedelta(seconds=60)).isoformat(),'valid_until':now.isoformat()},
               'future':{'as_of':(now+timedelta(seconds=1)).isoformat(),'valid_until':(now+timedelta(seconds=60)).isoformat()},
               'long-window':{'valid_until':(now+timedelta(seconds=61)).isoformat()}, 'missing-expiry':{},
               'naive-time':{'as_of':now.replace(tzinfo=None).isoformat(),'valid_until':(now+timedelta(seconds=60)).replace(tzinfo=None).isoformat()}}
    cases = {}
    for name, change in changes.items():
        statement = credentials.sign({**body,**change},key)
        statement['proof']['verificationMethod']=credential['issuer']+'#key-1'
        if name == 'unsigned':
            statement.pop('proof')
        if name == 'tampered':
            statement['as_of']=(now-timedelta(seconds=1)).isoformat()
        if name == 'missing-expiry':
            unsigned = {k:v for k,v in body.items() if k != 'valid_until'}
            statement=credentials.sign(unsigned,key)
        keys = {} if name == 'untrusted-key' else {credential['issuer']:public}
        cases[name]={'statement':statement,'credential':copy.deepcopy(credential),'trusted_keys':keys,'now':now.isoformat()}
    return cases


def starter_status(case):
    return credentials.checked_status(case['statement'],case['credential'],case['trusted_keys'],now=datetime.fromisoformat(case['now'])) == 'active'


def holder_key(case):
    """Reference extractor; a pass covers key binding only, not signature or holder proof."""
    try:
        subject=case['credential']['credentialSubject']
        values=[subject[k] for k in ('holderKey','publicKey') if k in subject]
        if not values or any(not isinstance(v,str) for v in values) or len(set(values)) != 1:
            return False
        value=values[0]
        if not value.startswith('ed25519:'):
            return False
        raw=base64.b64decode(value[8:]+'='*(-len(value[8:])%4),altchars=b'-_',validate=True)
        return len(raw)==32 and value==case['expected_key']
    except (KeyError, TypeError, ValueError):
        return False
