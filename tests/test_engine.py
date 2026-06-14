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
        m = engine.add("auth.py handles JWT token refresh logic")
        assert m.id.startswith("rm_")
        assert "auth" in m.content
        assert m.category == "note"

    def test_add_with_category(self, engine):
        m = engine.add("Use Redis cache for session tokens", category="pattern")
        assert m.category == "pattern"

    def test_add_auto_sentiment(self, engine):
        m = engine.add("Critical bug: the payment service crashes on empty input")
        # Should detect negative/anxious sentiment
        assert m.sentiment != "neutral"

    def test_add_with_tags(self, engine):
        m = engine.add("test content", tags=["api", "auth"])
        assert "api" in m.tags

    def test_add_with_file_refs(self, engine):
        m = engine.add("handles JWT tokens", file_refs=["services/api/auth.py"])
        assert "services/api/auth.py" in m.file_refs

    def test_add_auto_links(self, engine):
        engine.add("user authentication flow using session tokens")
        m2 = engine.add("user authentication module validates session tokens")
        # Should auto-link due to keyword overlap
        assert len(m2.linked_ids) > 0

    def test_add_to_global(self, engine):
        m = engine.add("timeout errors on slow connections", layer="global")
        assert m.layer == "global"


@pytest.mark.unit
class TestRecall:

    def test_recall_by_keyword(self, engine):
        engine.add("auth.py handles JWT token refresh logic", category="pattern")
        engine.add("database migration script for users table", category="note")
        engine.add("CSS fix for dark mode toggle", category="solution")

        results = engine.recall("JWT token refresh")
        assert len(results) > 0
        assert "auth" in results[0].memory.content

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
        engine.add("caching strategies for web applications", layer="global")
        engine.add("caching strategies for web applications", layer="project")

        results = engine.recall("caching strategies")
        # Project memory should rank higher due to 1.2x boost
        assert results[0].memory.layer == "project"

    def test_recall_score_breakdown(self, engine):
        engine.add("rate-limit bug fix for api")
        results = engine.recall("rate-limit api")
        r = results[0]
        assert r.keyword_score >= 0.0
        assert r.recency_score >= 0.0
        assert r.importance_score >= 0.0
        assert r.total_score > 0.0


@pytest.mark.unit
class TestTaskConditionedRecall:
    """M2: recall steered by current task state (open file + error signature)."""

    def test_file_affinity_boosts_matching_memory(self, engine):
        engine.add("connection pool tuning notes for the client", file_refs=["src/net/client.py"])
        engine.add("connection pool tuning notes for the server", file_refs=["src/other.py"])
        # Same query relevance; the memory tied to the current file should win.
        results = engine.recall("connection pool tuning", context_files=["src/net/client.py"])
        assert results[0].memory.file_refs == ["src/net/client.py"]
        assert results[0].task_affinity > 0.0

    def test_error_signature_surfaces_experience_card(self, engine):
        # An experience card whose problem matches an error...
        failure = engine.record_failure(
            "ConnectionResetError: peer reset during TLS handshake on the socket",
            file_refs=["src/net/client.py"],
        )
        # ...plus an unrelated but lexically-queryable memory.
        engine.add("notes on the deployment checklist and release cadence", category="note")

        # Query words don't match the card; the error signature does.
        results = engine.recall(
            "deployment checklist",
            error_signature="ConnectionResetError peer reset TLS handshake socket",
        )
        ids = [r.memory.id for r in results]
        assert failure.id in ids  # surfaced purely via error affinity
        card = next(r for r in results if r.memory.id == failure.id)
        assert card.task_affinity > 0.0

    def test_task_match_passes_relevance_floor(self, engine):
        # Zero lexical overlap with the query, but references the current file.
        engine.add("arbitrary content with no query words", file_refs=["src/net/client.py"])
        results = engine.recall("xyzzy nonsense", context_files=["src/net/client.py"])
        assert len(results) == 1
        assert results[0].task_affinity > 0.0

    def test_empty_query_with_task_state_returns_only_affine(self, engine):
        engine.add("relevant to the open file", file_refs=["src/net/client.py"])
        engine.add("unrelated recent memory about something else", file_refs=["src/zzz.py"])
        results = engine.recall("", context_files=["src/net/client.py"])
        assert len(results) == 1
        assert results[0].memory.file_refs == ["src/net/client.py"]

    def test_no_task_state_is_unchanged(self, engine):
        engine.add("rate-limit bug in the api gateway", category="failure")
        plain = engine.recall("rate-limit api")
        assert len(plain) >= 1
        assert all(r.task_affinity == 0.0 for r in plain)


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
        engine.add("handles JWT tokens", file_refs=["services/api/auth.py"])
        results = engine.links("auth.py")
        assert len(results) == 1

    def test_links_by_content(self, engine):
        engine.add("The API gateway has a rate-limit bug")
        results = engine.links("gateway")
        assert len(results) == 1

    def test_links_by_tag(self, engine):
        engine.add("some content", tags=["api"])
        results = engine.links("api")
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
