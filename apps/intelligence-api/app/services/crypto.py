from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

DEFAULT_FALLBACK_SALT = b"intentlead-credential-encryption-salt-v1"


def derive_fernet_key(key_material: Optional[str] = None) -> bytes:
    """
    Derives a valid 32-byte URL-safe base64-encoded Fernet key.
    - If key_material is already a valid Fernet key (44 chars urlsafe base64), uses it.
    - Otherwise, deterministically hashes key_material using SHA-256 and base64 encodes it.
    - If key_material is empty, falls back to a deterministic application salt for zero-crash local dev.
    """
    if not key_material or not key_material.strip():
        derived = hashlib.sha256(DEFAULT_FALLBACK_SALT).digest()
        return base64.urlsafe_b64encode(derived)

    raw = key_material.strip().encode("utf-8")
    # Check if already a valid 32-byte urlsafe base64 key
    if len(raw) == 44:
        try:
            decoded = base64.urlsafe_b64decode(raw)
            if len(decoded) == 32:
                return raw
        except Exception:
            pass

    # Hash arbitrary passphrase to 32 bytes and urlsafe base64 encode
    derived = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(derived)


def encrypt_credential(plaintext: str, key_material: Optional[str] = None) -> str:
    """
    Encrypts a plaintext credential using Fernet authenticated symmetric encryption.
    """
    if not plaintext:
        return ""
    fernet_key = derive_fernet_key(key_material)
    cipher = Fernet(fernet_key)
    token = cipher.encrypt(plaintext.strip().encode("utf-8"))
    return token.decode("utf-8")


def decrypt_credential(ciphertext: str, key_material: Optional[str] = None) -> str:
    """
    Decrypts a credential token.
    If the ciphertext does not start with 'gAAAAA' (the standard Fernet header),
    it is treated as a legacy plaintext credential and returned intact to ensure
    zero data destruction during migration.
    """
    if not ciphertext:
        return ""

    clean = ciphertext.strip()
    if not clean.startswith("gAAAAA"):
        # Legacy unencrypted credential
        return clean

    fernet_key = derive_fernet_key(key_material)
    cipher = Fernet(fernet_key)
    try:
        decrypted = cipher.decrypt(clean.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Decryption failed: Invalid encryption key or corrupted ciphertext") from exc


def rotate_credential(ciphertext: str, old_key: Optional[str], new_key: str) -> str:
    """
    Safely rotates an encrypted credential from old_key to new_key.
    """
    plaintext = decrypt_credential(ciphertext, old_key)
    return encrypt_credential(plaintext, new_key)


def mask_credential(credential: str) -> str:
    """
    Masks credential for safe UI display and logs, never exposing the plaintext.
    """
    return "•••• •••• •••• ••••"
