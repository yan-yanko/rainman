"""
Audit log tests (Phase 1b)
===========================

Opt-in append-only audit of store / recall / forget events.
"""

import json
import os
import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.audit import AuditLogger


def _read_log(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.mark.unit
class TestAuditOptIn:
    def test_disabled_by_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RAINMAN_AUDIT", raising=False)
        engine = RainmanEngine(project_dir=str(tmp_path))
        assert engine.audit.enabled is False
        engine.add(content="something worth remembering here", source="cli")
        engine.audit.flush()
        assert not os.path.exists(engine.store.audit_path())

    def test_enabled_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RAINMAN_AUDIT", "1")
        engine = RainmanEngine(project_dir=str(tmp_path))
        assert engine.audit.enabled is True


@pytest.mark.unit
class TestAuditEvents:
    @pytest.fixture
    def engine(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RAINMAN_AUDIT", "1")
        monkeypatch.setenv("RAINMAN_AUTHOR", "alice")
        return RainmanEngine(project_dir=str(tmp_path))

    def test_store_event_recorded(self, engine):
        m = engine.add(content="a deliberate memory about auth", source="cli")
        engine.audit.flush()
        entries = _read_log(engine.store.audit_path())
        store_events = [e for e in entries if e["event"] == "store"]
        assert len(store_events) == 1
        assert store_events[0]["actor"] == "alice"
        assert m.id in store_events[0]["memory_ids"]
        assert store_events[0]["source"] == "cli"

    def test_recall_and_forget_recorded(self, engine):
        m = engine.add(content="rate limit handling in the gateway", source="cli")
        engine.recall("rate limit", limit=5)
        engine.forget(m.id)
        engine.audit.flush()
        events = [e["event"] for e in _read_log(engine.store.audit_path())]
        assert "store" in events
        assert "recall" in events
        assert "forget" in events

    def test_append_only_across_flushes(self, engine):
        engine.add(content="first memory entry for testing", source="cli")
        engine.audit.flush()
        n1 = len(_read_log(engine.store.audit_path()))
        engine.add(content="second memory entry for testing", source="cli")
        engine.audit.flush()
        n2 = len(_read_log(engine.store.audit_path()))
        assert n2 > n1  # appended, not rewritten


@pytest.mark.unit
class TestAuditResilience:
    def test_write_failure_does_not_raise(self, tmp_path):
        # Point the log at a path whose parent is a file -> makedirs/open fails.
        bad_parent = tmp_path / "afile"
        bad_parent.write_text("x")
        logger = AuditLogger(str(bad_parent / "audit.log"), enabled=True)
        logger.record("store", actor="bob", memory_ids=["m1"])
        logger.flush()  # must not raise


@pytest.mark.unit
class TestAuditChain:
    """Tamper-evident hash chain (governance): every record links to the
    previous one; editing or removing a mid-file record breaks verification."""

    def _log_some(self, path, events, enabled=True):
        logger = AuditLogger(path, enabled=enabled, buffer_limit=100)
        for e in events:
            logger.record(e, actor="alice", memory_ids=["m1"])
        logger.flush()
        return logger

    def test_records_are_chained(self, tmp_path):
        from rainman.core.audit import _link_hash
        path = str(tmp_path / "audit.jsonl")
        self._log_some(path, ["store", "recall", "forget"])
        recs = _read_log(path)
        assert all("h" in r for r in recs)
        prev = ""
        for r in recs:
            assert r["h"] == _link_hash(prev, r)
            prev = r["h"]

    def test_chain_continues_across_logger_instances(self, tmp_path):
        from rainman.core.audit import verify_chain
        path = str(tmp_path / "audit.jsonl")
        self._log_some(path, ["store"])
        self._log_some(path, ["recall"])  # new process, chain resumes from disk
        result = verify_chain(path)
        assert result["ok"] and result["hashed"] == 2 and result["legacy"] == 0

    def test_verify_detects_edited_record(self, tmp_path):
        from rainman.core.audit import verify_chain
        path = str(tmp_path / "audit.jsonl")
        self._log_some(path, ["store", "recall", "forget"])
        lines = open(path, encoding="utf-8").read().splitlines()
        doctored = json.loads(lines[1])
        doctored["actor"] = "mallory"  # rewrite history
        lines[1] = json.dumps(doctored, ensure_ascii=False)
        open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")

        result = verify_chain(path)
        assert result["ok"] is False
        assert result["first_bad_line"] == 2

    def test_verify_detects_deleted_record(self, tmp_path):
        from rainman.core.audit import verify_chain
        path = str(tmp_path / "audit.jsonl")
        self._log_some(path, ["store", "recall", "forget"])
        lines = open(path, encoding="utf-8").read().splitlines()
        del lines[1]  # drop a mid-file record
        open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")

        result = verify_chain(path)
        assert result["ok"] is False

    def test_legacy_records_tolerated(self, tmp_path):
        from rainman.core.audit import verify_chain
        path = str(tmp_path / "audit.jsonl")
        # Pre-chain file written by an older version (no "h").
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 1.0, "event": "store", "actor": "old"}) + "\n")
        self._log_some(path, ["recall"])
        result = verify_chain(path)
        assert result["ok"] is True
        assert result["legacy"] == 1 and result["hashed"] == 1

    def test_missing_file_is_clean(self, tmp_path):
        from rainman.core.audit import verify_chain
        result = verify_chain(str(tmp_path / "nope.jsonl"))
        assert result["ok"] is True and result.get("missing") is True
