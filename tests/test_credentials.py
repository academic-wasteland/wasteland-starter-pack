import copy
import unittest
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wasteland.credentials import checked_status, public_key, sign, verify


class CredentialTests(unittest.TestCase):
    def test_signed_status_freshness_binding_and_unknown(self):
        key = Ed25519PrivateKey.generate()
        now = datetime.now(UTC).replace(microsecond=0)
        credential = {'id':'urn:credential:1','issuer':'urn:issuer:one','credentialStatus':{'id':'urn:status:1'}}
        body = {'type':'CredentialStatusStatement','id':credential['id'],'credential':credential['id'],
                'status_id':'urn:status:1','issuer':credential['issuer'],'status':'active',
                'as_of':now.isoformat(),'valid_until':(now+timedelta(seconds=60)).isoformat()}
        trusted = {credential['issuer']: public_key(key)}
        statement = sign(body,key)
        self.assertTrue(verify(statement, public_key(key)))
        self.assertEqual(checked_status(statement,credential,trusted,now=now),'active')
        for status in ('revoked','suspended','unknown'):
            self.assertEqual(checked_status(sign({**body,'status':status},key),credential,trusted,now=now),status)
        for changes in ({'issuer':'urn:other'}, {'credential':'urn:other'}, {'status_id':'urn:other'},
                        {'valid_until':(now+timedelta(seconds=61)).isoformat()},
                        {'as_of':(now+timedelta(seconds=1)).isoformat()}):
            self.assertEqual(checked_status(sign({**body,**changes},key),credential,trusted,now=now),'unknown')
        self.assertEqual(checked_status(statement,credential,trusted,now=now+timedelta(seconds=60)),'unknown')
        self.assertEqual(checked_status(statement,credential,{},now=now),'unknown')
        forged = copy.deepcopy(statement);forged['status']='revoked'
        self.assertEqual(checked_status(forged,credential,trusted,now=now),'unknown')
