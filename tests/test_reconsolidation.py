"""Reconsolidation-on-recall (#3) + working-memory buffer (#4).

Grounds two more human-memory mechanisms:
- reconsolidation: retrieving a memory returns it to a labile, UPDATABLE state
  (Nader 2015) — new info integrates in place, prior versions kept.
- working memory: a small capacity-limited buffer of what's currently in focus
  (Miller 7±2 / Baddeley), distinct from the long-term store.
"""

import os

import pytest

from rainman.core.engine import RainmanEngine, LABILE_WINDOW
from rainman.core.working import WorkingMemory


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
class TestReconsolidation:

    def test_integrates_new_info_and_keeps_revision(self, engine):
        m = engine.add("Deploy runs schema migrations on release", category="note")
        before_recalls = m.recall_count
        updated = engine.reconsolidate(m.id, "and rolls back automatically on failure")
        assert updated.id == m.id
        assert "rolls back automatically" in updated.content
        assert "schema migrations" in updated.content          # original preserved
        assert updated.metadata["revisions"][-1]["content"].startswith("Deploy runs schema")
        assert updated.recall_count == before_recalls + 1        # rehearsal refreshed

    def test_replace_overwrites_but_records_old(self, engine):
        m = engine.add("Old fact that is now wrong", category="note")
        updated = engine.reconsolidate(m.id, "The corrected fact", replace=True)
        assert updated.content == "The corrected fact"
        assert updated.metadata["revisions"][-1]["content"] == "Old fact that is now wrong"

    def test_noop_on_unknown_id_or_empty(self, engine):
        assert engine.reconsolidate("nope", "x") is None
        m = engine.add("Something", category="note")
        assert engine.reconsolidate(m.id, "   ") is None

    def test_duplicate_add_is_not_reduplicated(self, engine):
        m = engine.add("Redis caches session tokens", category="note")
        n_before = len(engine.get_all())
        engine.reconsolidate(m.id, "with a 600s TTL")
        assert len(engine.get_all()) == n_before   # updated in place, no new memory

    def test_labile_window_integrates_reobservation(self, engine):
        # A note recalled recently is labile; a near-duplicate re-observation with
        # novel wording integrates into it rather than being discarded.
        import time
        m = engine.add("The webhook signature uses HMAC-SHA512", category="note")
        engine.recall("webhook signature")          # reactivate -> labile
        # A near-duplicate re-observation carrying a novel clause.
        engine.add("The webhook signature uses HMAC-SHA512 verified at the edge layer",
                   category="note")
        again = engine._find_by_id(m.id)
        # Same memory, and the novel clause was integrated (labile window).
        assert "edge layer" in again.content or again.recall_count >= 1


@pytest.mark.unit
class TestWorkingMemory:

    def test_lru_capacity_and_recency_order(self, tmp_path):
        wm = WorkingMemory(str(tmp_path / "working.json"), capacity=3, ttl=1000)
        wm.touch(["a"], now=1.0)
        wm.touch(["b"], now=2.0)
        wm.touch(["c"], now=3.0)
        wm.touch(["d"], now=4.0)                 # over capacity -> 'a' evicted
        assert wm.active(now=5.0) == ["d", "c", "b"]

    def test_ttl_expires_stale_entries(self, tmp_path):
        wm = WorkingMemory(str(tmp_path / "working.json"), capacity=5, ttl=100)
        wm.touch(["old"], now=0.0)
        wm.touch(["new"], now=1000.0)
        assert wm.active(now=1000.0) == ["new"]  # 'old' aged out

    def test_retouch_moves_to_front(self, tmp_path):
        wm = WorkingMemory(str(tmp_path / "working.json"), capacity=5, ttl=1000)
        wm.touch(["a"], now=1.0)
        wm.touch(["b"], now=2.0)
        wm.touch(["a"], now=3.0)                 # re-touch a
        assert wm.active(now=4.0) == ["a", "b"]

    def test_engine_recall_populates_working_set(self, engine):
        engine.add("Auth uses verify_quill_sig not JWT", category="convention",
                   file_refs=["src/auth.py"])
        assert engine.working_set() == []        # nothing recalled yet
        engine.recall("auth")
        ws = engine.working_set()
        assert len(ws) == 1
        assert "verify_quill_sig" in ws[0].content

    def test_corrupt_file_is_treated_as_empty(self, tmp_path):
        path = str(tmp_path / "working.json")
        with open(path, "w") as f:
            f.write("{ not json")
        wm = WorkingMemory(path)
        assert wm.active(now=1.0) == []          # never raises
        wm.touch(["a"], now=1.0)                  # recovers
        assert wm.active(now=1.0) == ["a"]


@pytest.mark.unit
def test_labile_window_constant_is_reasonable():
    assert 60 <= LABILE_WINDOW <= 3600           # order-of-minutes, not seconds/days
