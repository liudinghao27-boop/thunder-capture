"""Helpers for encrypting user-provided secrets at rest.

Key rotation notes:
- Secrets are encrypted with a Fernet key derived from THUNDER_ENCRYPTION_KEY
  (preferred) or THUNDER_SECRET_KEY.
- If you rotate the encryption key, previously encrypted secrets will fail to
  decrypt. Plan rotation by re-encrypting secrets with the new key before
  retiring the old one, or accept that old secrets must be re-entered.
"""

import base64
import hashlib
import os

import logging

from cryptography.fernet import Fernet, InvalidToken

from server.config import SECRET_KEY

_PREFIX = "enc:v1:"
_fernet: Fernet | None = None
logger = logging.getLogger("thunder.secret_store")


def _derive_fernet_key(raw: str) -> bytes:
    """Accept a Fernet key or derive one from arbitrary secret material."""
    raw = raw.strip()
    if raw:
        try:
            Fernet(raw.encode("utf-8"))
            return raw.encode("utf-8")
        except Exception:
            pass
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        material = os.getenv("THUNDER_ENCRYPTION_KEY", "") or SECRET_KEY
        _fernet = Fernet(_derive_fernet_key(material))
    return _fernet


def encrypt_secret(value: str | None) -> str:
    """Encrypt a secret. Empty values remain empty."""
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(_PREFIX):
        return value
    token = _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return _PREFIX + token


def decrypt_secret(value: str | None) -> str:
    """Decrypt a secret, falling back to legacy plaintext values."""
    value = value or ""
    if not value.startswith(_PREFIX):
        return value
    token = value[len(_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning(
            "Failed to decrypt a secret (InvalidToken). "
            "This usually means the encryption key has changed. "
            "Re-enter the secret or restore the previous THUNDER_ENCRYPTION_KEY."
        )
        return ""


def mask_secret(value: str | None) -> str:
    plain = decrypt_secret(value)
    if not plain:
        return ""
    if len(plain) <= 8:
        return "****"
    return plain[:4] + "****" + plain[-4:]


def has_secret(value: str | None) -> bool:
    return bool(decrypt_secret(value).strip())
