"""Verify real signatures, claims, renewal, exclusive headers and key validation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from custom_components.qweather.auth import JWTAuth
from custom_components.qweather.api import QWeatherClient
from custom_components.qweather.settings import normalize


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_signature_claims_renewal_and_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            key = Ed25519PrivateKey.generate()
            path = Path(folder)/"key.pem"
            path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            data = {"auth_type":"jwt", "key_id":"test-kid", "developer_id":"test-issuer", "project_id":"test-project", "private_key_file":str(path)}
            auth = JWTAuth(data)
            with patch("custom_components.qweather.auth.time.time", return_value=2000000000):
                headers = auth.headers()
                token = headers["Authorization"].removeprefix("Bearer ")
                self.assertEqual(jwt.get_unverified_header(token), {"alg":"EdDSA", "kid":"test-kid"})
                claims = jwt.decode(token, key.public_key(), algorithms=["EdDSA"], options={"verify_exp":False,"verify_iat":False})
                self.assertEqual(claims, {"iss":"test-issuer", "sub":"test-project", "iat":1999999970, "exp":2000000900})
            with patch("custom_components.qweather.auth.time.time", return_value=2000000800):
                self.assertEqual(auth.headers(), headers)
            with patch("custom_components.qweather.auth.time.time", return_value=2000000840):
                self.assertNotEqual(auth.headers(), headers)
            with patch("custom_components.qweather.auth.time.time", return_value=1999999000):
                self.assertLess(jwt.decode(auth.headers()["Authorization"][7:],options={"verify_signature":False})["iat"],2000000000)
            class Response:
                status=200
                async def __aenter__(self): return self
                async def __aexit__(self,*args): pass
                async def json(self): return {}
            class Session:
                def get(self,url,**kwargs):
                    self.headers=kwargs["headers"]
                    return Response()
            session=Session()
            client=QWeatherClient(session,"test.re.qweatherapi.com","unused-key",28.22,112.92,extras=["air","alerts","minutely"],auth=auth)
            for path in ("/weather/v1/current/28.22/112.92","/airquality/v1/current/28.22/112.92","/weatheralert/v1/current/28.22/112.92","/v7/minutely/5m"):
                await client._request(path)
                self.assertEqual(set(session.headers),{"Authorization"})

    async def test_invalid_key_and_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"bad.pem"
            path.write_text("not a private key")
            for filename in (str(path),str(path)+"-missing"):
                with self.assertRaisesRegex(ValueError,"Ed25519"):
                    JWTAuth({"private_key_file":filename})
        common={"location":"112.92,28.22","api_host":"test.re.qweatherapi.com","api_key":"old-key"}
        data=normalize(common)
        self.assertEqual(data["auth_type"],"api_key")
        with self.assertRaises(ValueError): normalize({**common,"auth_type":"jwt"})
        data=normalize({**common,"auth_type":"jwt","key_id":"test","developer_id":"test","project_id":"test","private_key_file":"/config/test.pem"})
        self.assertNotIn("api_key",data)
