"""
Write-side salience
====================

Auto-learn (the PostToolUse hook) sees every Read/Edit/Bash. Storing all of it
is the documented failure mode — the store fills with low-signal "read file X"
noise that drowns the few memories worth keeping. The research is blunt about
this: curation quality moves downstream agent success more than retrieval
ranking does (Xiong et al., arXiv:2505.16067 — "add everything" *degrades*
results). So we gate writes on a cheap, code-specific salience score.

Zero-LLM, zero-dependency: keyword/heuristic signals only.
"""

from typing import List, Optional

# Something broke — the single highest-value signal for developer memory.
ERROR_SIGNALS = (
    "error", "exception", "traceback", "panic", "segfault", "segmentation",
    "crash", "fatal", "assert", "failed", "failure", "timeout", "deadlock",
)

# Touches a security- or config-sensitive surface — worth remembering.
SECURITY_SIGNALS = (
    "auth", "secret", "credential", "password", "token", "payment", "crypto",
    "security", "permission", "vulnerab", ".env", "config", "dockerfile",
    "deploy", "migration", "schema", "api key", "private key", "session",
)

# The developer flagged it as worth remembering.
INTENT_SIGNALS = (
    "todo", "fixme", "hack", "workaround", "deprecated", "regression",
    "important", "must ", "never ", "always ", "gotcha", "caveat", "note:",
)

# Command looks like a build/test/release action whose outcome matters.
BUILD_SIGNALS = (
    "pytest", "test", "build", "deploy", "migrate", "npm ", "yarn ", "make ",
    "cargo", "gradle", "mvn ", "tox", "lint", "release",
)

SALIENCE_THRESHOLD = 0.3


def salience_score(
    category: str,
    content: str,
    file_refs: Optional[List[str]] = None,
    command: str = "",
) -> float:
    """Score how worth-remembering a candidate auto-learned memory is, in [0,1].

    A failure/solution starts high (these are the experience cards that matter).
    Notes (file reads/edits) must earn their place via an error, security/config,
    or intent signal; a plain read of an ordinary file scores ~0 and is dropped.
    """
    text = " ".join(
        part for part in (content or "", " ".join(file_refs or []), command or "")
        if part
    ).lower()
    cmd = (command or "").lower()

    score = 0.0
    if category in ("failure", "solution"):
        score += 0.6
    if any(k in text for k in ERROR_SIGNALS):
        score += 0.3
    if any(k in text for k in SECURITY_SIGNALS):
        score += 0.3
    if any(k in text for k in INTENT_SIGNALS):
        score += 0.3
    if any(k in cmd for k in BUILD_SIGNALS):
        score += 0.3
    return min(1.0, score)


def is_salient(category: str, content: str,
               file_refs: Optional[List[str]] = None,
               command: str = "",
               threshold: float = SALIENCE_THRESHOLD) -> bool:
    """True if the candidate clears the salience threshold and is worth storing."""
    return salience_score(category, content, file_refs, command) >= threshold
