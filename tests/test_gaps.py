"""Skill-gap report tests: recurring-failure clustering, ranking, and the
engine/CLI wiring. The report is the store's answer to "which skill or
permanent fix should we write next?"."""

import os
import time

import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.gaps import gap_report, find_failure_clusters


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


def _fail(engine, problem, files):
    return engine.record_failure(problem, file_refs=files)


@pytest.mark.unit
class TestClustering:
    def test_recurring_failure_forms_one_cluster(self, engine):
        _fail(engine, "TimeoutError: QueuePool limit of size 5 reached, connection timed out", ["app/db.py"])
        _fail(engine, "TimeoutError: QueuePool limit of size 5 reached again under load", ["app/db.py"])
        _fail(engine, "QueuePool limit reached, connection timed out on checkout", ["app/db.py"])
        rows = engine.gaps()
        assert len(rows) == 1
        assert rows[0]["occurrences"] == 3
        assert "QueuePool" in rows[0]["problem"]
        assert "app/db.py" in rows[0]["files"]

    def test_unrelated_failures_do_not_merge(self, engine):
        _fail(engine, "TimeoutError: QueuePool limit of size 5 reached", ["app/db.py"])
        _fail(engine, "UnicodeEncodeError charmap codec cannot encode character", ["cli/report.py"])
        assert engine.gaps() == []  # two singletons, no recurrence

    def test_singletons_included_with_min_cluster_one(self, engine):
        _fail(engine, "TimeoutError: QueuePool limit of size 5 reached", ["app/db.py"])
        rows = engine.gaps(min_cluster=1)
        assert len(rows) == 1 and rows[0]["occurrences"] == 1

    def test_empty_store(self, engine):
        assert engine.gaps() == []


@pytest.mark.unit
class TestRankingAndFixes:
    def test_unresolved_recent_outranks_resolved_old(self, engine):
        now = time.time()
        # Cluster A: unresolved, recent (2 occurrences)
        a1 = _fail(engine, "SignatureMismatch webhook verification failed on partner callback", ["app/webhooks.py"])
        a2 = _fail(engine, "SignatureMismatch webhook verification failed again in sandbox", ["app/webhooks.py"])
        # Cluster B: resolved, old (2 occurrences, 60 days back)
        b1 = _fail(engine, "TimeoutError QueuePool limit of size 5 reached", ["app/db.py"])
        engine.resolve_failure(b1, "raise pool_size to 20 and enable pool_pre_ping")
        b2 = _fail(engine, "TimeoutError QueuePool limit reached under load", ["app/db.py"])
        engine.resolve_failure(b2, "raise pool_size to 20 and enable pool_pre_ping")
        for m in (b1, b2):
            m.timestamp = now - 60 * 86400
        # keep A fresh
        for m in (a1, a2):
            m.timestamp = now - 3600

        rows = gap_report([m for m in engine.get_all() if m.category == "failure"], now)
        assert rows[0]["unresolved"] is True
        assert "SignatureMismatch" in rows[0]["problem"] or "webhook" in rows[0]["problem"]
        assert rows[1]["unresolved"] is False

    def test_known_fix_surfaces_in_report(self, engine):
        f1 = _fail(engine, "TimeoutError QueuePool limit of size 5 reached", ["app/db.py"])
        engine.resolve_failure(f1, "raise pool_size to 20 and enable pool_pre_ping")
        _fail(engine, "TimeoutError QueuePool limit reached once more", ["app/db.py"])
        rows = engine.gaps()
        assert len(rows) == 1
        assert rows[0]["resolved_count"] == 1
        assert rows[0]["open_count"] == 1
        assert "pool_size to 20" in rows[0]["known_fix"]
        # a known fix exists, so the cluster is not "unresolved"
        assert rows[0]["unresolved"] is False

    def test_clusters_only_contain_failures(self, engine):
        # Solutions created by resolve_failure share tokens with the failure;
        # they must not inflate the cluster count.
        f1 = _fail(engine, "TimeoutError QueuePool limit of size 5 reached", ["app/db.py"])
        engine.resolve_failure(f1, "raise pool_size and enable pool_pre_ping")
        _fail(engine, "TimeoutError QueuePool limit of size 5 reached again", ["app/db.py"])
        clusters = find_failure_clusters(engine.get_all(), min_cluster=2)
        assert len(clusters) == 1
        assert all(m.category == "failure" for m in clusters[0])
        assert len(clusters[0]) == 2


@pytest.mark.unit
class TestCli:
    def test_cmd_gaps_smoke(self, engine, tmp_path, monkeypatch, capsys):
        _fail(engine, "TimeoutError QueuePool limit of size 5 reached", ["app/db.py"])
        _fail(engine, "TimeoutError QueuePool limit reached under load", ["app/db.py"])
        from rainman.cli import commands
        monkeypatch.setattr(commands, "_get_engine", lambda: engine)
        commands.cmd_gaps()
        out = capsys.readouterr().out
        assert "keep getting stuck" in out
        assert "2×" in out
        assert "app/db.py" in out

    def test_cmd_gaps_empty(self, engine, monkeypatch, capsys):
        from rainman.cli import commands
        monkeypatch.setattr(commands, "_get_engine", lambda: engine)
        commands.cmd_gaps()
        out = capsys.readouterr().out
        assert "No recurring struggles" in out
