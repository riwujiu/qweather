"""QWeather Ed25519 JWT signing with automatic short-lived token renewal."""
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class JWTAuth:
    def __init__(self, data):
        # Construct in HA's executor: reading and parsing a PEM must not block it.
        try:
            key = serialization.load_pem_private_key(Path(data["private_key_file"]).read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError
        except (OSError, ValueError, TypeError):
            raise ValueError("Unable to load an unencrypted Ed25519 private key") from None
        self._key = key
        self._kid = data["key_id"]
        self._issuer = data["developer_id"]
        self._subject = data["project_id"]
        self._token = None
        self._issued = 0
        self._expires = 0

    def headers(self):
        now = int(time.time())
        if self._token is None or now >= self._expires - 60 or now < self._issued:
            self._issued = now - 30
            self._expires = now + 900
            self._token = jwt.encode(
                {"iss": self._issuer, "sub": self._subject, "iat": self._issued, "exp": self._expires},
                self._key, algorithm="EdDSA", headers={"kid": self._kid, "typ": None},
            )
        return {"Authorization": f"Bearer {self._token}"}


async def async_auth(hass, data):
    if data.get("auth_type", "api_key") == "jwt":
        return await hass.async_add_executor_job(JWTAuth, data)
    return None
