"""Tests for typed-causal experience cards + failure->fix pairing (M1)."""

import os
import time

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
class TestExperienceCards:

    def test_record_failure_creates_open_card(self, engine):
        m = engine.record_failure(
            problem="test_login asserted 200 but got 401",
            command="pytest tests/test_auth.py",
            file_refs=["tests/test_auth.py"],
        )
        assert m is not None
        assert m.category == "failure"
        exp = m.metadata["experience"]
        assert exp["outcome"] == "open"
        assert "401" in exp["problem"]
        assert exp["fix"] is None

    def test_record_failure_rejects_empty(self, engine):
        assert engine.record_failure(problem="   ") is None

    def test_find_open_failure_matches_on_file_overlap(self, engine):
        engine.record_failure("boom", command="pytest tests/test_auth.py",
                              file_refs=["tests/test_auth.py"])
        found = engine.find_open_failure(["tests/test_auth.py", "src/other.py"])
        assert found is not None
        assert "boom" in found.metadata["experience"]["problem"]

    def test_find_open_failure_no_overlap_returns_none(self, engine):
        engine.record_failure("boom", file_refs=["tests/test_auth.py"])
        assert engine.find_open_failure(["totally/unrelated.py"]) is None

    def test_find_open_failure_respects_time_window(self, engine):
        m = engine.record_failure("boom", file_refs=["a.py"])
        # Backdate the failure beyond the window.
        m.timestamp = time.time() - 10 * 86400
        assert engine.find_open_failure(["a.py"], within_seconds=86400) is None

    def test_resolve_failure_pairs_and_links(self, engine):
        failure = engine.record_failure(
            "test_login asserted 200 but got 401",
            command="pytest tests/test_auth.py",
            file_refs=["tests/test_auth.py"],
        )
        solution = engine.resolve_failure(failure, fix="widened the token TTL check")

        assert solution is not None
        assert solution.category == "solution"
        # The failure card is flipped to resolved and cross-linked.
        assert failure.metadata["experience"]["outcome"] == "resolved"
        assert failure.metadata["experience"]["resolved_by"] == solution.id
        assert solution.id in failure.linked_ids
        assert failure.id in solution.linked_ids
        # The solution carries the causal chain: same problem, the fix, the link.
        sol_exp = solution.metadata["experience"]
        assert sol_exp["fix"] == "widened the token TTL check"
        assert sol_exp["resolved_failure"] == failure.id
        assert "401" in sol_exp["problem"]

    def test_resolved_failure_no_longer_pairs(self, engine):
        """Once resolved, a failure must not be paired again by a later pass."""
        failure = engine.record_failure("boom", file_refs=["a.py"])
        engine.resolve_failure(failure, fix="fixed it")
        assert engine.find_open_failure(["a.py"]) is None

    def test_pairing_survives_reload(self, tmp_path):
        """The resolved state + links must persist to disk."""
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        e1 = RainmanEngine(project_dir=project, global_dir=global_dir)
        e1.store.init_project(project)
        e1.store.init_global()
        failure = e1.record_failure("boom on auth", file_refs=["tests/test_auth.py"])
        e1.resolve_failure(failure, fix="patched the guard")

        e2 = RainmanEngine(project_dir=project, global_dir=global_dir)
        reloaded = e2.find_open_failure(["tests/test_auth.py"])
        assert reloaded is None  # already resolved on disk
        all_mem = e2.get_all()
        cats = sorted(m.category for m in all_mem)
        assert cats == ["failure", "solution"]
