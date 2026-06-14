"""Tests for local consolidation: dedup/merge + supersession (M5)."""

import os

import pytest

from rainman.core.engine import RainmanEngine


@pytest.fixture
def engine(tmp_path):
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    return e


@pytest.mark.unit
class TestDedup:

    def test_near_duplicate_note_is_merged_not_duplicated(self, engine):
        first = engine.add("the deploy script rotates the TLS certificates nightly")
        second = engine.add("the deploy script rotates the TLS certificates nightly")
        assert second.id == first.id              # merged into the existing note
        assert len(engine.get_all()) == 1
        assert second.recall_count == 1           # reinforced (re-observed)

    def test_distinct_notes_are_not_merged(self, engine):
        engine.add("the deploy script rotates the TLS certificates nightly")
        engine.add("the billing webhook validates the stripe signature header")
        assert len(engine.get_all()) == 2

    def test_merge_unions_file_refs_and_tags(self, engine):
        engine.add("cache warmer preloads the product catalog on boot",
                   file_refs=["a.py"], tags=["cache"])
        merged = engine.add("cache warmer preloads the product catalog on boot",
                            file_refs=["b.py"], tags=["perf"])
        assert set(merged.file_refs) == {"a.py", "b.py"}
        assert set(merged.tags) == {"cache", "perf"}

    def test_experience_cards_are_never_merged(self, engine):
        engine.record_failure("the same flaky assertion keeps failing here",
                             file_refs=["t.py"])
        engine.record_failure("the same flaky assertion keeps failing here",
                             file_refs=["t.py"])
        # Failure cards are intentional — two distinct cards, not merged.
        assert len([m for m in engine.get_all() if m.category == "failure"]) == 2


@pytest.mark.unit
class TestSupersession:

    def test_supersession_hides_old_memory(self, engine):
        old = engine.add("we use Redis for caching user sessions in production")
        new = engine.add("we no longer use Redis for caching sessions, migrated to Memcached")

        # Old memory is retired (kept for the record, hidden from recall).
        old_reloaded = engine._find_by_id(old.id)
        assert old_reloaded.metadata.get("superseded_by") == new.id
        # Still present in the full set (history preserved).
        assert any(m.id == old.id for m in engine.get_all())

    def test_superseded_excluded_from_recall(self, engine):
        engine.add("we use Redis for caching user sessions in production")
        engine.add("we no longer use Redis for caching sessions, migrated to Memcached")
        results = engine.recall("Redis caching sessions")
        ids_contents = [r.memory.content for r in results]
        assert not any("we use Redis" in c for c in ids_contents)
        assert any("Memcached" in c for c in ids_contents)

    def test_no_marker_no_supersession(self, engine):
        engine.add("we use Redis for caching user sessions in production")
        # Heavy overlap but NO supersession marker -> both kept (deduped only if
        # near-identical, which this isn't).
        engine.add("Redis caching for user sessions tuned with a longer TTL value")
        visible = [m for m in engine._visible()]
        assert len(visible) == 2

    def test_supersession_persists_across_reload(self, tmp_path):
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        e1 = RainmanEngine(project_dir=project, global_dir=global_dir)
        e1.store.init_project(project)
        e1.store.init_global()
        e1.add("we use Redis for caching user sessions in production")
        e1.add("we no longer use Redis for caching sessions, migrated to Memcached")

        e2 = RainmanEngine(project_dir=project, global_dir=global_dir)
        results = e2.recall("Redis caching sessions")
        assert not any("we use Redis" in r.memory.content for r in results)
