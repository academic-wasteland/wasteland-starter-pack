"""Optional Ed25519 holder and signed-status helpers (`pip install .[credentials]`).

Trust keys are supplied by the receiver, never inferred from a relay reply.
The wire format matches PangenomeTownEd25519Jcs2026, not W3C Data Integrity.
"""
import base64
import json
from datetime import UTC, datetime

PROOF = 'PangenomeTownEd25519Jcs2026'


def canonical(document):
    return json.dumps({k: v for k, v in document.items() if k != 'proof'},
                      sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def public_key(key):
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return 'ed25519:' + base64.urlsafe_b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode().rstrip('=')


def sign(document, key):
    return {**document, 'proof': {'type': PROOF, 'proofValue': base64.urlsafe_b64encode(key.sign(canonical(document))).decode().rstrip('=')}}


def verify(document, trusted_key):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        if not trusted_key.startswith('ed25519:') or document['proof']['type'] != PROOF:
            return False
        decode = lambda text: base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
        key = Ed25519PublicKey.from_public_bytes(decode(trusted_key.split(':', 1)[1]))
        key.verify(decode(document['proof']['proofValue']), canonical(document))
        return True
    except (ValueError, KeyError, TypeError, AttributeError, InvalidSignature):
        return False


def call(client, town, operation, body):
    mid = client.ask(town, operation=operation, body=body)
    replies = client.wait(mid, timeout=30)
    for reply in replies:
        if reply['from'] == town and reply['kind'] == 'answer' and reply['in_reply_to'] == mid:
            if reply['body'].get('ok') is not True:
                raise ValueError(reply['body'].get('error', 'credential request failed'))
            return reply['body']
    raise ValueError('no authenticated reply from authority')


def holder_request(client, town, key, holder, *, application, action='apply'):
    """Submit an application dict or fetch an application ID, proving key possession."""
    request = {'action': action, 'holder': holder, 'publicKey': public_key(key), 'application': application}
    result = call(client, town, 'credential-challenge', {'request': request})
    challenge = result['challenge']
    if (challenge.get('type') != 'CredentialRelayProof' or challenge.get('audience') != town
            or challenge.get('sender') != client.config['name'] or challenge.get('request') != request):
        raise ValueError('authority returned a mismatched challenge')
    return call(client, town, 'credential-apply' if action == 'apply' else 'credential-fetch',
                {'presentation': sign(challenge, key)})


def checked_status(statement, credential, trusted_keys, *, now=None):
    """Return active/revoked/suspended or unknown; strictly bounded 60-second freshness."""
    try:
        issuer = credential['issuer']
        if (statement['type'] != 'CredentialStatusStatement' or statement['issuer'] != issuer
                or statement['credential'] != credential['id']
                or statement['status_id'] != credential['credentialStatus']['id']
                or statement['id'] not in (credential['id'], credential['credentialStatus']['id'])
                or not verify(statement, trusted_keys[issuer])):
            return 'unknown'
        moment = now or datetime.now(UTC)
        start = datetime.fromisoformat(statement['as_of'])
        end = datetime.fromisoformat(statement['valid_until'])
        if not start <= moment < end or not 0 < (end-start).total_seconds() <= 60:
            return 'unknown'
        return statement['status'] if statement['status'] in ('active', 'revoked', 'suspended') else 'unknown'
    except (KeyError, TypeError, ValueError, AttributeError):
        return 'unknown'


def status_checker(client, issuer_towns, trusted_keys):
    """Fresh status_checker callback for the existing presentation verifier.

Call verification before execution and again before release. No positive cache.
Issuer->town and issuer->key maps are receiver configuration, not discovery trust.
"""
    def check(credential):
        try:
            issuer = credential['issuer']
            reply = call(client, issuer_towns[issuer], 'credential-status',
                         {'id': credential['id'], 'issuer': issuer})
            return checked_status(reply['statement'], credential, trusted_keys)
        except Exception:  # noqa: BLE001 - Transport and malformed data always fail closed.
            return 'unknown'
    return check
