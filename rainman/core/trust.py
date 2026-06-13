"""
Trust levels
============

Every memory has a trust level derived from its ``source`` — *who/what* taught
it. Trust is the spine of Rainman's memory-poisoning defense.

    user   — a developer stored it deliberately (cli, mcp, or empty/legacy)
    hook   — auto-learned from the developer's own session (post_tool_use, ...)
    ingest — third-party content stored verbatim (git history, repo files)

Design contract (see THREAT_MODEL):

  * Display is unconditional — every injected memory shows its trust + source
    so the model and the human can discount appropriately.
  * The poisoning *defense* is gating (quarantine / auto-injection floor,
    wired by org policy), NOT ranking. An attacker controls the content that
    feeds the keyword score, so any fixed ranking penalty can be out-stuffed.
  * Ranking carries only a small, honest *quality* prior (curated > auto-learned
    > ingested), surfaced in the RecallResult breakdown like any other
    component. It is a tiebreaker, never a security boundary.
  * Low-trust memories are denied the score *amplifiers* (rehearsal, and
    associative boost flowing down from higher-trust anchors) — this closes the
    rich-get-richer feedback loop a poisoned memory would otherwise ride.

Unknown/empty source maps to ``user``: legacy memories predate trust and the
attacker-controlled paths (ingest/hook) are the ones we positively classify, so
benefit-of-the-doubt here costs nothing security-wise.
"""

USER = "user"
HOOK = "hook"
INGEST = "ingest"

# Higher rank == more trusted.
RANK = {USER: 3, HOOK: 2, INGEST: 1}

# Small, visible quality prior (NOT a security control — see module docstring).
QUALITY_PRIOR = {USER: 1.0, HOOK: 0.95, INGEST: 0.85}


def trust_level(source: str) -> str:
    """Map a memory ``source`` string to its trust level."""
    s = (source or "").lower()
    if s.startswith("hook:"):
        return HOOK
    if s.startswith("ingest:") or s.startswith("git:"):
        return INGEST
    # cli, mcp, empty, or anything we don't positively classify as third-party.
    return USER


def trust_rank(source: str) -> int:
    """Numeric trust rank (higher == more trusted)."""
    return RANK[trust_level(source)]


def quality_prior(source: str) -> float:
    """Quality-prior multiplier for ranking (tiebreaker only)."""
    return QUALITY_PRIOR[trust_level(source)]
