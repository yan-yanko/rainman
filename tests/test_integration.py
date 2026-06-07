"""Integration tests — engine + store round-trip with real disk I/O."""

import json
import os
import time
import pytest

from rainman.core.engine import RainmanEngine, MAX_MEMORIES
from rainman.core.models import Memory


@pytest.fixture
def dirs(tmp_path):
    """Create temp project + global directories, return (project, global)."""
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    return project, global_dir


def _fresh_engine(project, global_dir):
    """Create a new engine instance (simulates restart)."""
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    return e


@pytest.mark.unit
class TestRoundTrip:
    """Full add -> persist -> reload -> recall cycle with real disk."""

    def test_add_recall_across_restart(self, dirs):
        project, global_dir = dirs
        e1 = _fresh_engine(project, global_dir)
        e1.add("auth.py handles JWT token refresh logic",
               category="pattern", tags=["api"])

        # New engine instance — must load from disk
        e2 = _fresh_engine(project, global_dir)
        results = e2.recall("JWT token refresh")
        assert len(results) >= 1
        assert "auth" in results[0].memory.content
        assert results[0].memory.category == "pattern"
        assert "api" in results[0].memory.tags

    def test_multiple_adds_persist(self, dirs):
        project, global_dir = dirs
        e1 = _fresh_engine(project, global_dir)
        e1.add("first memory about auth")
        e1.add("second memory about database")
        e1.add("third memory about caching")

        e2 = _fresh_engine(project, global_dir)
        assert len(e2.get_all()) == 3

    def test_forget_persists_across_restart(self, dirs):
        project, global_dir = dirs
        e1 = _fresh_engine(project, global_dir)
        m = e1.add("temporary note to delete")
        e1.forget(m.id)

        e2 = _fresh_engine(project, global_dir)
        assert len(e2.get_all()) == 0

    def test_recall_count_persists(self, dirs):
        project, global_dir = dirs
        e1 = _fresh_engine(project, global_dir)
        e1.add("important knowledge about caching strategies")
        e1.recall("caching strategies")
        e1.recall("caching strategies")

        e2 = _fresh_engine(project, global_dir)
        results = e2.recall("caching strategies")
        # recall_count should be 2 from e1 + 1 from this recall = 3
        assert results[0].memory.recall_count == 3


@pytest.mark.unit
class TestLayeredStorage:
    """Global + project layers stored in separate files, merged on recall."""

    def test_layers_in_separate_files(self, dirs):
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        e.add("project-specific note", layer="project")
        e.add("cross-project learning", layer="global")

        # Check separate files on disk
        proj_path = os.path.join(project, ".rainman", "memories.json")
        glob_path = os.path.join(global_dir, "memories.json")

        with open(proj_path, encoding="utf-8") as f:
            proj_data = json.load(f)
        with open(glob_path, encoding="utf-8") as f:
            glob_data = json.load(f)

        assert len(proj_data) == 1
        assert len(glob_data) == 1
        assert "project-specific" in proj_data[0]["content"]
        assert "cross-project" in glob_data[0]["content"]

    def test_merged_recall(self, dirs):
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        e.add("project auth pattern", layer="project")
        e.add("global auth best practice", layer="global")

        results = e.recall("auth")
        assert len(results) == 2
        # Project should rank higher due to 1.2x boost
        assert results[0].memory.layer == "project"

    def test_project_layer_survives_restart(self, dirs):
        project, global_dir = dirs
        e1 = _fresh_engine(project, global_dir)
        e1.add("project memory", layer="project")
        e1.add("global memory", layer="global")

        e2 = _fresh_engine(project, global_dir)
        all_mem = e2.get_all()
        layers = {m.layer for m in all_mem}
        assert layers == {"project", "global"}


@pytest.mark.unit
class TestAutoLinking:
    """Auto-linking via keyword overlap."""

    def test_related_memories_get_linked(self, dirs):
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        m1 = e.add("payment service handles token validation using Redis cache")
        m2 = e.add("payment service has race condition in token validation logic")
        # m2 should be auto-linked to m1 due to keyword overlap
        assert len(m2.linked_ids) > 0

    def test_unrelated_memories_not_linked(self, dirs):
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        e.add("CSS styling for dark mode toggle component")
        m2 = e.add("database migration script for PostgreSQL users table")
        # No meaningful keyword overlap
        assert len(m2.linked_ids) == 0

    def test_manual_link_persists(self, dirs):
        project, global_dir = dirs
        e1 = _fresh_engine(project, global_dir)
        m1 = e1.add("first concept")
        m2 = e1.add("second concept")
        e1.link(m1.id, m2.id)

        e2 = _fresh_engine(project, global_dir)
        all_mem = e2.get_all()
        by_id = {m.id: m for m in all_mem}
        assert m2.id in by_id[m1.id].linked_ids
        assert m1.id in by_id[m2.id].linked_ids

    def test_associative_boost_on_recall(self, dirs):
        """Linked memories should get associative boost in phase 2."""
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        m1 = e.add("rate-limit bug is a critical problem in the API", category="failure")
        m2 = e.add("auth module solves rate-limit bug with token bucket", category="solution")
        # Manually link them
        e.link(m1.id, m2.id)

        results = e.recall("rate-limit bug API")
        # Both should appear — m2 gets associative boost from being linked to m1
        ids_returned = [r.memory.id for r in results]
        assert m1.id in ids_returned
        assert m2.id in ids_returned


@pytest.mark.unit
class TestSaveOne:
    """save_one() upserts — doesn't duplicate on repeated saves."""

    def test_save_one_does_not_duplicate(self, dirs):
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        m = e.add("test memory")

        # save_one again (simulating recall updating access stats)
        m.recall_count = 5
        e.store.save_one(m)

        # Reload and check — should still be 1 memory, not 2
        e2 = _fresh_engine(project, global_dir)
        assert len(e2.get_all()) == 1
        results = e2.recall("test memory")
        assert results[0].memory.recall_count == 6  # 5 + 1 from this recall


@pytest.mark.unit
class TestSaveLayers:
    """save_layers() only rewrites specified layers."""

    def test_save_layers_project_only(self, dirs):
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        e.add("project note", layer="project")
        e.add("global note", layer="global")

        # Get file mod times
        proj_path = os.path.join(project, ".rainman", "memories.json")
        glob_path = os.path.join(global_dir, "memories.json")
        glob_mtime_before = os.path.getmtime(glob_path)

        # Small delay to ensure mtime changes would be detectable
        time.sleep(0.05)

        # save_layers with only "project"
        e.store.save_layers(e.get_all(), {"project"})
        glob_mtime_after = os.path.getmtime(glob_path)

        # Global file should NOT have been rewritten
        assert glob_mtime_after == glob_mtime_before


@pytest.mark.unit
class TestDiskFormat:
    """Verify on-disk JSON format is correct and human-readable."""

    def test_json_is_readable(self, dirs):
        project, global_dir = dirs
        e = _fresh_engine(project, global_dir)
        e.add("test memory content", category="pattern", tags=["auth", "jwt"],
              file_refs=["services/auth.py"])

        path = os.path.join(project, ".rainman", "memories.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) == 1
        entry = data[0]
        assert entry["content"] == "test memory content"
        assert entry["category"] == "pattern"
        assert entry["tags"] == ["auth", "jwt"]
        assert entry["file_refs"] == ["services/auth.py"]
        assert entry["layer"] == "project"
        assert "id" in entry
        assert "timestamp" in entry
        assert "importance" in entry
