"""
Review queue tests (Phase 2c)
==============================

Quarantined memories can be listed, approved (become recallable), or
rejected (removed). Each decision is audited.
"""

import json
import os
import pytest

from rainman.core import trust
from rainman.core.engine import RainmanEngine


def _write_policy(project_dir, policy):
    path = os.path.join(project_dir, ".rainman", "config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(policy, f)


@pytest.fixture(autouse=True)
def _no_real_org_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("RAINMAN_ORG_POLICY", str(tmp_path / "nope.json"))


@pytest.fixture
def engine(tmp_path):
    proj = str(tmp_path / "proj")
    _write_policy(proj, {"quarantine_ingest": True})
    return RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "glob"))


@pytest.mark.unit
class TestReviewQueue:
    def test_quarantined_listed(self, engine):
        engine.add(content="ingested note about rate limits from repo", source="ingest:files")
        pending = engine.list_quarantined()
        assert len(pending) == 1
        assert pending[0].trust == trust.INGEST

    def test_approve_makes_recallable(self, engine):
        m = engine.add(content="ingested note about caching strategy", source="ingest:files")
        assert engine.recall("caching", limit=10) == []  # quarantined -> hidden
        assert engine.review_approve(m.id) is True
        hits = engine.recall("caching", limit=10)
        assert any(r.memory.id == m.id for r in hits)
        assert engine.list_quarantined() == []

    def test_reject_removes(self, engine):
        m = engine.add(content="ingested suspicious instruction blob", source="ingest:files")
        assert engine.review_reject(m.id) is True
        assert engine.list_quarantined() == []
        assert all(x.id != m.id for x in engine.get_all())

    def test_approve_unknown_id_returns_false(self, engine):
        assert engine.review_approve("does-not-exist") is False

    def test_approve_non_quarantined_returns_false(self, engine):
        m = engine.add(content="a normal user memory not quarantined", source="cli")
        assert engine.review_approve(m.id) is False

    def test_decisions_are_audited(self, tmp_path, monkeypatch):
        proj = str(tmp_path / "proj")
        _write_policy(proj, {"quarantine_ingest": True, "audit": True})
        engine = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "glob"))
        a = engine.add(content="ingested item to approve later on", source="ingest:files")
        r = engine.add(content="ingested item to reject later on now", source="ingest:files")
        engine.review_approve(a.id)
        engine.review_reject(r.id)
        engine.audit.flush()
        with open(engine.store.audit_path(), encoding="utf-8") as f:
            events = [json.loads(line)["event"] for line in f if line.strip()]
        assert "review_approve" in events
        assert "review_reject" in events
