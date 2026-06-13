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
