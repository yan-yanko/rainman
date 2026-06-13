"""
Concurrency & Corruption Tests
================================

Tests for multi-thread writes, stale lock cleanup, corruption quarantine,
and malformed entry handling.
"""

import json
import os
import time
import threading
import pytest

from rainman.core.models import Memory
from rainman.core.store import MemoryStore, LOCK_STALE_AGE, LOCK_TIMEOUT, SCHEMA_VERSION


def _make_memory(mid, content="test", layer="project"):
    return Memory(
        id=mid,
        content=content,
        timestamp=time.time(),
        importance=0.5,
        category="note",
        sentiment="neutral",
        layer=layer,
    )


@pytest.mark.unit
class TestConcurrentWrites:
    """Multiple threads writing to the same store simultaneously."""

    def test_concurrent_writes_no_data_loss(self, tmp_path):
        """Two threads writing different memories — all should be persisted."""
        project_dir = str(tmp_path / "project")
        os.makedirs(os.path.join(project_dir, ".rainman"), exist_ok=True)
        memories_path = os.path.join(project_dir, ".rainman", "memories.json")
        with open(memories_path, "w") as f:
            json.dump([], f)

        errors = []
        n_per_thread = 5

        def writer(thread_id):
            try:
                store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
                for i in range(n_per_thread):
                    m = _make_memory(f"t{thread_id}_m{i}", f"content from thread {thread_id} item {i}")
                    store.save_one(m)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Writer threads had errors: {errors}"

        # Verify all memories are present
        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        all_memories = store.load_all()
        ids = {m.id for m in all_memories}

        expected = {f"t{t}_m{i}" for t in range(3) for i in range(n_per_thread)}
        assert expected == ids, f"Missing memories: {expected - ids}"

    def test_concurrent_read_modify_write(self, tmp_path):
        """Concurrent update_rehearsal_stats shouldn't lose updates."""
        project_dir = str(tmp_path / "project")
        os.makedirs(os.path.join(project_dir, ".rainman"), exist_ok=True)

        # Pre-populate with memories
        memories = [_make_memory(f"m{i}", f"memory {i}") for i in range(5)]
        memories_path = os.path.join(project_dir, ".rainman", "memories.json")
        with open(memories_path, "w") as f:
            json.dump([m.to_dict() for m in memories], f)

        errors = []

        def updater(thread_id):
            try:
                store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
                updates = {f"m{thread_id}": {"recall_count": 10, "last_recalled": time.time()}}
                store.update_rehearsal_stats(updates, "project")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Updater threads had errors: {errors}"

        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        all_memories = store.load_all()
        updated = {m.id: m.recall_count for m in all_memories if m.recall_count == 10}
        assert len(updated) == 5, f"Not all memories updated: {updated}"


@pytest.mark.unit
class TestStaleLock:
    """Stale lockfile detection and cleanup."""

    def test_stale_lock_gets_cleaned(self, tmp_path):
        """A lock older than LOCK_STALE_AGE should be removed automatically."""
        project_dir = str(tmp_path / "project")
        os.makedirs(os.path.join(project_dir, ".rainman"), exist_ok=True)
        memories_path = os.path.join(project_dir, ".rainman", "memories.json")
        with open(memories_path, "w") as f:
            json.dump([], f)

        # Create a stale lockfile
        lockfile = memories_path + ".lock"
        with open(lockfile, "w") as f:
            f.write("99999")  # Fake PID
        # Backdate it
        stale_time = time.time() - LOCK_STALE_AGE - 10
        os.utime(lockfile, (stale_time, stale_time))

        # Should still be able to write despite stale lock
        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        m = _make_memory("after_stale", "written after stale lock")
        store.save_one(m)

        all_memories = store.load_all()
        assert any(m.id == "after_stale" for m in all_memories)


    def test_live_lock_not_removed_on_timeout(self, tmp_path, monkeypatch):
        """A fresh (non-stale) lock held by a live writer must survive a
        timeout — clobbering it would let a competing writer corrupt the file."""
        project_dir = str(tmp_path / "project")
        os.makedirs(os.path.join(project_dir, ".rainman"), exist_ok=True)
        memories_path = os.path.join(project_dir, ".rainman", "memories.json")
        with open(memories_path, "w") as f:
            json.dump([], f)

        # Hold a *fresh* lock (not stale) for the whole acquire window.
        lockfile = memories_path + ".lock"
        with open(lockfile, "w") as f:
            f.write("12345")
        # Shrink the timeout so the test is fast.
        monkeypatch.setattr("rainman.core.store.LOCK_TIMEOUT", 0.2)

        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        m = _make_memory("contended", "should not clobber the live lock")
        with pytest.raises(TimeoutError):
            store.save_one(m)

        # The live lock must still be present — not force-removed.
        assert os.path.exists(lockfile)


@pytest.mark.unit
class TestSchemaVersion:
    """Schema version is stamped at init and readable for migrations."""

    def test_init_stamps_schema_version(self, tmp_path):
        project_dir = str(tmp_path / "project")
        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        store.init_project(project_dir)

        config_path = os.path.join(project_dir, ".rainman", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        assert config["schema_version"] == SCHEMA_VERSION
        assert store.schema_version("project") == SCHEMA_VERSION

    def test_legacy_store_reports_none(self, tmp_path):
        """A config without the key (pre-versioning store) returns None."""
        project_dir = str(tmp_path / "project")
        rainman_dir = os.path.join(project_dir, ".rainman")
        os.makedirs(rainman_dir, exist_ok=True)
        with open(os.path.join(rainman_dir, "config.json"), "w") as f:
            json.dump({"version": "0.1.0"}, f)

        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        assert store.schema_version("project") is None


@pytest.mark.unit
class TestCorruptionQuarantine:
    """Corrupted JSON files are quarantined, not silently wiped."""

    def test_corrupted_json_triggers_quarantine(self, tmp_path):
        """A corrupted memories.json should be renamed and not deleted."""
        project_dir = str(tmp_path / "project")
        rainman_dir = os.path.join(project_dir, ".rainman")
        os.makedirs(rainman_dir, exist_ok=True)

        memories_path = os.path.join(rainman_dir, "memories.json")
        with open(memories_path, "w") as f:
            f.write("{not valid json at all!!!}")

        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        result = store.load_all()

        # Should return empty (no crash)
        project_memories = [m for m in result if m.layer == "project"]
        assert project_memories == []

        # Original file should be quarantined (renamed)
        quarantined = [f for f in os.listdir(rainman_dir) if ".corrupt-" in f]
        assert len(quarantined) == 1

    def test_malformed_entries_skipped_valid_preserved(self, tmp_path):
        """Individual bad entries don't kill the whole store."""
        project_dir = str(tmp_path / "project")
        rainman_dir = os.path.join(project_dir, ".rainman")
        os.makedirs(rainman_dir, exist_ok=True)

        good_entry = _make_memory("good1", "valid memory").to_dict()
        bad_entry = {"id": "bad1"}  # Missing required fields
        good_entry2 = _make_memory("good2", "another valid memory").to_dict()

        memories_path = os.path.join(rainman_dir, "memories.json")
        with open(memories_path, "w") as f:
            json.dump([good_entry, bad_entry, good_entry2], f)

        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        result = store.load_all()

        project_memories = [m for m in result if m.layer == "project"]
        ids = {m.id for m in project_memories}
        assert "good1" in ids
        assert "good2" in ids
        assert "bad1" not in ids

    def test_empty_file_returns_empty(self, tmp_path):
        """An empty file should not crash."""
        project_dir = str(tmp_path / "project")
        rainman_dir = os.path.join(project_dir, ".rainman")
        os.makedirs(rainman_dir, exist_ok=True)

        memories_path = os.path.join(rainman_dir, "memories.json")
        with open(memories_path, "w") as f:
            f.write("")

        store = MemoryStore(project_dir=project_dir, global_dir=str(tmp_path / "global"))
        result = store.load_all()
        project_memories = [m for m in result if m.layer == "project"]
        assert project_memories == []


@pytest.mark.unit
class TestInputValidation:
    """Input validation in engine.add()."""

    def test_short_content_rejected(self, tmp_path):
        from rainman.core.engine import RainmanEngine
        engine = RainmanEngine(project_dir=str(tmp_path))
        result = engine.add(content="hi")
        assert result is None

    def test_invalid_category_falls_back_to_note(self, tmp_path):
        from rainman.core.engine import RainmanEngine
        engine = RainmanEngine(project_dir=str(tmp_path))
        m = engine.add(content="this is a valid memory content", category="invalid_cat")
        assert m is not None
        assert m.category == "note"

    def test_content_truncated_at_max(self, tmp_path):
        from rainman.core.engine import RainmanEngine, MAX_CONTENT_LENGTH
        engine = RainmanEngine(project_dir=str(tmp_path))
        long_content = "x" * (MAX_CONTENT_LENGTH + 1000)
        m = engine.add(content=long_content)
        assert m is not None
        assert len(m.content) == MAX_CONTENT_LENGTH

    def test_invalid_layer_falls_back_to_project(self, tmp_path):
        from rainman.core.engine import RainmanEngine
        engine = RainmanEngine(project_dir=str(tmp_path))
        m = engine.add(content="valid content for testing", layer="invalid")
        assert m is not None
        assert m.layer == "project"

    def test_tags_sanitized(self, tmp_path):
        from rainman.core.engine import RainmanEngine, MAX_TAGS
        engine = RainmanEngine(project_dir=str(tmp_path))
        tags = [f"tag{i}" for i in range(MAX_TAGS + 10)]
        m = engine.add(content="valid content for testing", tags=tags)
        assert m is not None
        assert len(m.tags) == MAX_TAGS


@pytest.mark.unit
class TestRefresh:
    """Engine.refresh() method."""

    def test_refresh_updates_timestamp(self, tmp_path):
        from rainman.core.engine import RainmanEngine
        engine = RainmanEngine(project_dir=str(tmp_path))
        m = engine.add(content="memory to refresh later")
        old_ts = m.timestamp
        old_count = m.recall_count

        time.sleep(0.01)
        result = engine.refresh(m.id)
        assert result is True
        assert m.timestamp > old_ts
        assert m.recall_count == old_count + 1

    def test_refresh_nonexistent_returns_false(self, tmp_path):
        from rainman.core.engine import RainmanEngine
        engine = RainmanEngine(project_dir=str(tmp_path))
        result = engine.refresh("nonexistent_id")
        assert result is False
