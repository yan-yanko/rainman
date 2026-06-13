"""
Trust & provenance tests (Phase 1a)
====================================

Trust derivation, the score-amplifier denial for low-trust memories,
the associative trust restriction, the visible quality prior, author
provenance, and the recall/context trust floor.
"""

import time
import pytest

from rainman.core import trust
from rainman.core.models import Memory
from rainman.core.scoring import (
    keyword_score,
    temporal_decay,
    associative_score,
    compute_score,
)
from rainman.core.engine import RainmanEngine


def _mem(mid, content="rate limit bug in api", source="", recall_count=0, linked_ids=None):
    return Memory(
        id=mid,
        content=content,
        timestamp=time.time(),
        importance=0.5,
        category="note",
        sentiment="neutral",
        source=source,
        recall_count=recall_count,
        linked_ids=linked_ids or [],
    )


@pytest.mark.unit
class TestTrustDerivation:
    def test_levels(self):
        assert trust.trust_level("cli") == trust.USER
        assert trust.trust_level("mcp") == trust.USER
        assert trust.trust_level("") == trust.USER
        assert trust.trust_level("hook:post_tool_use:Read") == trust.HOOK
        assert trust.trust_level("ingest:files") == trust.INGEST
        assert trust.trust_level("git:abc123") == trust.INGEST

    def test_rank_ordering(self):
        assert trust.trust_rank("cli") > trust.trust_rank("hook:x")
        assert trust.trust_rank("hook:x") > trust.trust_rank("ingest:files")

    def test_memory_trust_property(self):
        assert _mem("a", source="git:deadbeef").trust == trust.INGEST


@pytest.mark.unit
class TestAmplifierDenial:
    """Low-trust (ingest) memories don't accrue rehearsal multipliers."""

    def test_keyword_rehearsal_denied_for_ingest(self):
        user = _mem("u", source="cli", recall_count=10)
        ingest = _mem("i", source="ingest:files", recall_count=10)
        # Same content/query; user gets the 2x rehearsal boost, ingest does not.
        assert keyword_score(user, ["rate", "limit"]) > keyword_score(ingest, ["rate", "limit"])

    def test_keyword_rehearsal_kept_for_hook(self):
        hook0 = _mem("h0", source="hook:post_tool_use:Read", recall_count=0)
        hook10 = _mem("h10", source="hook:post_tool_use:Read", recall_count=10)
        assert keyword_score(hook10, ["rate"]) > keyword_score(hook0, ["rate"])

    def test_temporal_rehearsal_denied_for_ingest(self):
        ts = time.time() - 5 * 86400
        user = _mem("u", source="cli", recall_count=10)
        ingest = _mem("i", source="ingest:files", recall_count=10)
        user.timestamp = ingest.timestamp = ts
        assert temporal_decay(user) > temporal_decay(ingest)


@pytest.mark.unit
class TestAssociativeRestriction:
    """Boost must not flow from a higher-trust anchor down to a lower-trust entry."""

    def test_ingest_entry_blocked_from_user_anchor(self):
        # Ingested memory links itself to a high-trust anchor in top-K.
        anchor = _mem("anchor", source="cli")
        poisoned = _mem("poison", source="ingest:files", linked_ids=["anchor"])
        entries = [anchor, poisoned]
        trust_index = {m.id: trust.trust_rank(m.source) for m in entries}

        # Without restriction: gets the boost. With restriction: zero.
        unrestricted = associative_score("poison", entries, ["anchor"], entry=poisoned)
        restricted = associative_score(
            "poison", entries, ["anchor"], entry=poisoned, trust_index=trust_index
        )
        assert unrestricted > 0
        assert restricted == 0.0

    def test_same_trust_anchor_still_boosts(self):
        a = _mem("a", source="ingest:files")
        b = _mem("b", source="ingest:files", linked_ids=["a"])
        entries = [a, b]
        trust_index = {m.id: trust.trust_rank(m.source) for m in entries}
        assert associative_score("b", entries, ["a"], entry=b, trust_index=trust_index) > 0


@pytest.mark.unit
class TestQualityPrior:
    def test_prior_in_breakdown_and_total(self):
        ingest = _mem("i", source="ingest:files")
        scores = compute_score(ingest, ["rate", "limit"])
        assert scores["trust_prior"] == trust.QUALITY_PRIOR[trust.INGEST]
        # total is the weighted sum scaled by the prior (< raw sum for ingest)
        raw = (
            0.35 * scores["keyword"] + 0.25 * scores["recency"]
            + 0.20 * scores["importance"] + 0.20 * scores["associative"]
        )
        assert scores["total"] == pytest.approx(raw * trust.QUALITY_PRIOR[trust.INGEST])

    def test_user_prior_is_identity(self):
        user = _mem("u", source="cli")
        scores = compute_score(user, ["rate", "limit"])
        assert scores["trust_prior"] == 1.0


@pytest.mark.unit
class TestProvenanceAndFloor:
    def test_author_stamped_on_add(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RAINMAN_AUTHOR", "alice")
        engine = RainmanEngine(project_dir=str(tmp_path))
        m = engine.add(content="a deliberately stored memory", source="cli")
        assert m.author == "alice"

    def test_recall_min_trust_gates_ingest(self, tmp_path):
        engine = RainmanEngine(project_dir=str(tmp_path))
        engine.add(content="user note about rate limit handling", source="cli")
        engine.add(content="ingested rate limit note from repo", source="ingest:files")

        all_hits = engine.recall("rate limit", limit=10)
        gated = engine.recall("rate limit", limit=10, min_trust=trust.HOOK)
        assert any(r.memory.trust == trust.INGEST for r in all_hits)
        assert all(r.memory.trust != trust.INGEST for r in gated)

    def test_context_min_trust_gates_ingest(self, tmp_path):
        engine = RainmanEngine(project_dir=str(tmp_path))
        engine.add(content="user decision about architecture", source="cli", category="decision")
        engine.add(content="ingested third party content", source="ingest:files")
        ctx = engine.context(limit=10, min_trust=trust.HOOK)
        assert all(r.memory.trust != trust.INGEST for r in ctx)
