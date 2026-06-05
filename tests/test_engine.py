"""Tests for Rainman engine — add, recall, link, context."""

import os
import tempfile
import time
import pytest
from rainman.core.engine import RainmanEngine


@pytest.fixture
def engine(tmp_path):
    """Create an engine with temp directories for both layers."""
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project, exist_ok=True)
    os.makedirs(global_dir, exist_ok=True)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    return e


@pytest.mark.unit
class TestAdd:

    def test_add_returns_memory(self, engine):
        m = engine.add("political_identity.py assigns party ID using ANES data")
        assert m.id.startswith("rm_")
        assert "political_identity" in m.content
        assert m.category == "note"

    def test_add_with_category(self, engine):
        m = engine.add("Use ANES data for party assignment", category="pattern")
        assert m.category == "pattern"

    def test_add_auto_sentiment(self, engine):
        m = engine.add("Critical bug: the election predictor crashes on empty input")
        # Should detect negative/anxious sentiment
        assert m.sentiment != "neutral"

    def test_add_with_tags(self, engine):
        m = engine.add("test content", tags=["election", "bias"])
        assert "election" in m.tags

    def test_add_with_file_refs(self, engine):
        m = engine.add("assigns party ID", file_refs=["engine/election/predictor.py"])
        assert "engine/election/predictor.py" in m.file_refs

    def test_add_auto_links(self, engine):
        engine.add("political identity assignment using ANES survey data")
        m2 = engine.add("political identity module assigns party ID from survey")
        # Should auto-link due to keyword overlap
        assert len(m2.linked_ids) > 0

    def test_add_to_global(self, engine):
        m = engine.add("Claude has RLHF bias on political content", layer="global")
        assert m.layer == "global"


@pytest.mark.unit
class TestRecall:

    def test_recall_by_keyword(self, engine):
        engine.add("political_identity.py assigns party ID without LLM", category="pattern")
        engine.add("database migration script for users table", category="note")
        engine.add("CSS fix for dark mode toggle", category="solution")

        results = engine.recall("party ID assignment")
        assert len(results) > 0
        assert "political_identity" in results[0].memory.content

    def test_recall_empty_store(self, engine):
        results = engine.recall("anything")
        assert results == []

    def test_recall_respects_limit(self, engine):
        for i in range(20):
            engine.add(f"Memory number {i} about different topics")
        results = engine.recall("memory", limit=3)
        assert len(results) == 3

    def test_recall_by_category(self, engine):
        engine.add("auth bug in login flow", category="failure")
        engine.add("auth pattern for JWT tokens", category="pattern")
        results = engine.recall("auth", category="failure")
        assert all(r.memory.category == "failure" for r in results)

    def test_recall_updates_access_count(self, engine):
        engine.add("important pattern to remember")
        results = engine.recall("important pattern")
        assert results[0].memory.recall_count == 1

        results2 = engine.recall("important pattern")
        assert results2[0].memory.recall_count == 2

    def test_project_boost(self, engine):
        engine.add("global knowledge about LLM bias", layer="global")
        engine.add("project-specific LLM bias in predictor", layer="project")

        results = engine.recall("LLM bias")
        # Project memory should rank higher due to 1.2x boost
        assert results[0].memory.layer == "project"

    def test_recall_score_breakdown(self, engine):
        engine.add("election voting bias solution")
        results = engine.recall("election voting")
        r = results[0]
        assert r.keyword_score >= 0.0
        assert r.recency_score >= 0.0
        assert r.importance_score >= 0.0
        assert r.total_score > 0.0


@pytest.mark.unit
class TestContext:

    def test_context_returns_recent(self, engine):
        engine.add("recent memory about auth")
        results = engine.context(limit=5)
        assert len(results) > 0

    def test_context_no_query_needed(self, engine):
        engine.add("first memory")
        engine.add("second memory")
        # context() doesn't need a query — returns recent + important
        results = engine.context()
        assert len(results) == 2


@pytest.mark.unit
class TestLinks:

    def test_links_by_file_ref(self, engine):
        engine.add("assigns party ID", file_refs=["engine/election/predictor.py"])
        results = engine.links("predictor.py")
        assert len(results) == 1

    def test_links_by_content(self, engine):
        engine.add("The predictor module has a voting bias")
        results = engine.links("predictor")
        assert len(results) == 1

    def test_links_by_tag(self, engine):
        engine.add("some content", tags=["election"])
        results = engine.links("election")
        assert len(results) == 1

    def test_manual_link(self, engine):
        m1 = engine.add("first memory")
        m2 = engine.add("second memory")
        assert engine.link(m1.id, m2.id) is True
        assert m2.id in m1.linked_ids
        assert m1.id in m2.linked_ids


@pytest.mark.unit
class TestForget:

    def test_forget_removes_memory(self, engine):
        m = engine.add("temporary note")
        assert engine.forget(m.id) is True
        assert len(engine.get_all()) == 0

    def test_forget_nonexistent(self, engine):
        assert engine.forget("rm_nonexistent_123") is False


@pytest.mark.unit
class TestPersistence:

    def test_save_and_reload(self, tmp_path):
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)

        # Create and add
        e1 = RainmanEngine(project_dir=project, global_dir=global_dir)
        e1.store.init_project(project)
        e1.store.init_global()
        e1.add("persistent memory about auth patterns", category="pattern")

        # Reload from disk
        e2 = RainmanEngine(project_dir=project, global_dir=global_dir)
        results = e2.recall("auth patterns")
        assert len(results) > 0
        assert "auth patterns" in results[0].memory.content

    def test_layered_persistence(self, tmp_path):
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)

        e1 = RainmanEngine(project_dir=project, global_dir=global_dir)
        e1.store.init_project(project)
        e1.store.init_global()
        e1.add("project-specific note", layer="project")
        e1.add("global learning", layer="global")

        # Reload
        e2 = RainmanEngine(project_dir=project, global_dir=global_dir)
        all_memories = e2.get_all()
        layers = {m.layer for m in all_memories}
        assert "project" in layers
        assert "global" in layers


@pytest.mark.unit
class TestStats:

    def test_stats_counts(self, engine):
        engine.add("bug report", category="failure")
        engine.add("fix applied", category="solution")
        engine.add("general note", category="note")
        stats = engine.get_stats()
        assert stats["total"] == 3
        assert stats["by_category"]["failure"] == 1
        assert stats["by_category"]["solution"] == 1
