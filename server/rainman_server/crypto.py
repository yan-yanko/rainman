"""
Encryption at rest (server)
===========================

Encrypts the confidential payload — the synced memory content stored in
``items.data`` — with **AES-256-GCM** (authenticated). Opt-in: set
``RAINMAN_DB_KEY`` (a 32-byte key, hex or base64) to enable; unset means the
data column is stored as plaintext JSON exactly as before (backward compatible).

Each value is sealed with a fresh random 96-bit nonce and tagged
``enc:v1:<base64(nonce||ciphertext+tag)>`` so encrypted and legacy-plaintext
rows can coexist (e.g. while migrating, or if the key is introduced later).

Scope: ``items.data`` (memory content). Metadata/index columns and the audit
log stay queryable plaintext; rely on host full-disk encryption for those.
Bearer tokens are separately hashed (never reversible). Part of the SERVER
package, where dependencies are allowed.
"""

import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "enc:v1:"
_NONCE = 12  # 96-bit GCM nonce
_cache = {}  # raw-key -> AESGCM, to avoid rebuilding per row


def _load_key() -> Optional[bytes]:
    raw = os.environ.get("RAINMAN_DB_KEY", "").strip()
    if not raw:
        return None
    # Accept 64-char hex or base64; must decode to exactly 32 bytes.
    try:
        if len(raw) == 64:
            key = bytes.fromhex(raw)
        else:
            key = base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error) as e:
        raise ValueError(f"RAINMAN_DB_KEY must be 32 bytes as hex or base64: {e}")
    if len(key) != 32:
        raise ValueError("RAINMAN_DB_KEY must decode to 32 bytes (AES-256)")
    return key


def _cipher() -> Optional[AESGCM]:
    key = _load_key()
    if key is None:
        return None
    if key not in _cache:
        _cache[key] = AESGCM(key)
    return _cache[key]


def encryption_enabled() -> bool:
    return _load_key() is not None


def seal(plaintext: str) -> str:
    """Encrypt a string for storage. No-op (returns plaintext) when no key set."""
    cipher = _cipher()
    if cipher is None:
        return plaintext
    nonce = os.urandom(_NONCE)
    ct = cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def unseal(stored: str) -> str:
    """Decrypt a stored value. Plaintext (non-prefixed) values pass through, so
    legacy rows still read. Raises if an encrypted value is read without a key."""
    if not stored.startswith(_PREFIX):
        return stored
    cipher = _cipher()
    if cipher is None:
        raise RuntimeError("RAINMAN_DB_KEY is required to read encrypted data")
    blob = base64.b64decode(stored[len(_PREFIX):])
    nonce, ct = blob[:_NONCE], blob[_NONCE:]
    return cipher.decrypt(nonce, ct, None).decode("utf-8")


def generate_key() -> str:
    """A fresh 32-byte key as hex, for RAINMAN_DB_KEY."""
    return os.urandom(32).hex()
