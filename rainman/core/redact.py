"""
Secret Redaction
=================

Prevents auto-learn hooks from storing sensitive content in memories.json.
Two layers of protection:

1. Path denylist — skip storing entirely for sensitive file types
2. Content redaction — replace known secret patterns with [REDACTED]

Conservative: false redaction of a hash is acceptable; a leaked key is not.
"""

import re
from typing import Optional


# File paths that should never be auto-learned
SENSITIVE_PATH_PATTERNS = [
    ".env",
    ".env.",        # .env.local, .env.production, etc.
    ".pem",
    "_rsa",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    "credentials",
    "secrets",
    "secret_key",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    ".keystore",
    ".htpasswd",
    "shadow",
    "token.json",
    "service_account",
]

# Content patterns that indicate secrets (compiled for speed)
_SECRET_PATTERNS = [
    # AWS access keys
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # AWS secret keys (40-char base64 after = or :)
    re.compile(r"(?:aws_secret_access_key|AWS_SECRET)\s*[=:]\s*[A-Za-z0-9/+=]{40}"),
    # GitHub tokens (classic and fine-grained)
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
    # GitHub App tokens
    re.compile(r"ghu_[A-Za-z0-9]{36,}"),
    # Generic API key/secret/token/password assignments
    re.compile(
        r"(?:api[_-]?key|api[_-]?secret|password|passwd|secret|token|auth[_-]?token|access[_-]?token|private[_-]?key)"
        r"\s*[=:]\s*['\"]?[A-Za-z0-9/+=_\-]{8,}['\"]?",
        re.IGNORECASE,
    ),
    # PEM private key headers
    re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
    # Bearer tokens
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    # Base64 blobs (64+ chars of base64 — likely a key or cert)
    re.compile(r"[A-Za-z0-9+/]{64,}={0,2}"),
    # Connection strings with passwords
    re.compile(r"://[^:]+:[^@\s]+@", re.IGNORECASE),
]


def is_sensitive_path(file_path: str) -> bool:
    """Check if a file path matches the sensitive denylist."""
    if not file_path:
        return False

    # Normalize path separators
    normalized = file_path.replace("\\", "/").lower()
    basename = normalized.split("/")[-1] if "/" in normalized else normalized

    for pattern in SENSITIVE_PATH_PATTERNS:
        if pattern in basename or pattern in normalized:
            return True

    return False


def redact_content(content: str) -> str:
    """Replace known secret patterns with [REDACTED]."""
    if not content:
        return content

    result = content
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)

    return result


def safe_content(content: str, file_path: Optional[str] = None) -> Optional[str]:
    """
    Full safety check for auto-learned content.
    Returns None if the file should be skipped entirely.
    Returns redacted content otherwise.
    """
    if file_path and is_sensitive_path(file_path):
        return None

    redacted = redact_content(content)

    # If redaction removed most of the content, skip it
    if len(redacted.replace("[REDACTED]", "").strip()) < 20:
        return None

    return redacted
