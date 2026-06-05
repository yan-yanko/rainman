"""Tests for retrieval scoring functions."""

import time
import pytest
from rainman.core.models import Memory
from rainman.core.scoring import (
    keyword_score,
    temporal_decay,
    importance_boost,
    associative_score,
    compute_score,
    WEIGHTS,
)


def _make_memory(content="test content", category="note", **kwargs):
    defaults = {
        "id": f"rm_test_{id(content)}",
        "content": content,
        "timestamp": time.time(),
        "importance": 0.5,
        "category": category,
    }
    defaults.update(kwargs)
    return Memory(**defaults)


@pytest.mark.unit
class TestKeywordScore:

    def test_exact_match(self):
        m = _make_memory("political identity assignment module")
        score = keyword_score(m, ["political", "identity"])
        assert score > 0.0

    def test_no_match(self):
        m = _make_memory("database migration script")
        score = keyword_score(m, ["election", "voting"])
        assert score == 0.0

    def test_partial_match(self):
        m = _make_memory("election voting bias in predictor")
        score = keyword_score(m, ["election", "database"])
        assert 0.0 < score < 1.0

    def test_rehearsal_boost(self):
        m1 = _make_memory("voting module", recall_count=0)
        m2 = _make_memory("voting module", recall_count=10)
        s1 = keyword_score(m1, ["voting"])
        s2 = keyword_score(m2, ["voting"])
        assert s2 > s1

    def test_empty_query(self):
        m = _make_memory("anything here")
        assert keyword_score(m, []) == 0.0

    def test_tag_match(self):
        m = _make_memory("some content", tags=["election", "bias"])
        score = keyword_score(m, ["election"])
        assert score > 0.0

    def test_file_ref_match(self):
        m = _make_memory("assigns party ID", file_refs=["engine/election/predictor.py"])
        score = keyword_score(m, ["predictor"])
        assert score > 0.0


@pytest.mark.unit
class TestTemporalDecay:

    def test_recent_memory_high_score(self):
        m = _make_memory(timestamp=time.time())
        score = temporal_decay(m)
        assert score > 0.8

    def test_old_memory_low_score(self):
        m = _make_memory(timestamp=time.time() - 30 * 86400)  # 30 days ago
        score = temporal_decay(m)
        assert score < 0.5

    def test_rehearsal_slows_decay(self):
        ts = time.time() - 14 * 86400  # 14 days ago
        m1 = _make_memory(timestamp=ts, recall_count=0)
        m2 = _make_memory(timestamp=ts, recall_count=5)
        assert temporal_decay(m2) > temporal_decay(m1)

    def test_very_old_memory(self):
        m = _make_memory(timestamp=time.time() - 365 * 86400)  # 1 year ago
        score = temporal_decay(m)
        assert score < 0.1


@pytest.mark.unit
class TestImportanceBoost:

    def test_failure_highest(self):
        m = _make_memory(category="failure")
        assert importance_boost(m) >= 0.85

    def test_note_lowest(self):
        m = _make_memory(category="note")
        assert importance_boost(m) <= 0.5

    def test_keyword_boost(self):
        m1 = _make_memory("updated the docs", category="note")
        m2 = _make_memory("critical bug fix in production", category="note")
        assert importance_boost(m2) > importance_boost(m1)

    def test_category_ordering(self):
        failure = importance_boost(_make_memory(category="failure"))
        solution = importance_boost(_make_memory(category="solution"))
        decision = importance_boost(_make_memory(category="decision"))
        note = importance_boost(_make_memory(category="note"))
        assert failure > solution > decision > note


@pytest.mark.unit
class TestAssociativeScore:

    def test_linked_to_top_result(self):
        m1 = _make_memory("voting bias", id="m1")
        m2 = _make_memory("party assignment", id="m2", linked_ids=["m1"])
        score = associative_score("m2", [m1, m2], top_ids=["m1"])
        assert score > 0.0

    def test_no_links(self):
        m1 = _make_memory("voting bias", id="m1")
        m2 = _make_memory("database schema", id="m2")
        score = associative_score("m2", [m1, m2], top_ids=["m1"])
        assert score == 0.0

    def test_reverse_link(self):
        m1 = _make_memory("voting bias", id="m1", linked_ids=["m2"])
        m2 = _make_memory("party assignment", id="m2")
        score = associative_score("m2", [m1, m2], top_ids=["m1"])
        assert score > 0.0

    def test_capped_at_06(self):
        # Even with many links, cap at 0.6
        m1 = _make_memory("a", id="m1")
        m2 = _make_memory("b", id="m2")
        m3 = _make_memory("c", id="m3", linked_ids=["m1", "m2"])
        score = associative_score("m3", [m1, m2, m3], top_ids=["m1", "m2"])
        assert score <= 0.6


@pytest.mark.unit
class TestComputeScore:

    def test_returns_all_components(self):
        m = _make_memory("election voting bias")
        result = compute_score(m, ["election", "voting"])
        assert "total" in result
        assert "keyword" in result
        assert "recency" in result
        assert "importance" in result
        assert "associative" in result

    def test_total_is_weighted_sum(self):
        m = _make_memory("election voting bias")
        result = compute_score(m, ["election", "voting"])
        expected = (
            WEIGHTS["keyword"] * result["keyword"]
            + WEIGHTS["recency"] * result["recency"]
            + WEIGHTS["importance"] * result["importance"]
            + WEIGHTS["associative"] * result["associative"]
        )
        assert abs(result["total"] - expected) < 0.001

    def test_relevant_query_scores_higher(self):
        m = _make_memory("election voting bias in the predictor module")
        relevant = compute_score(m, ["election", "voting", "bias"])
        irrelevant = compute_score(m, ["database", "migration", "schema"])
        assert relevant["total"] > irrelevant["total"]
