"""
Policy control plane tests (Phase 1c)
======================================

Precedence (org.enforce > project > user > org.defaults > builtin),
enforce-locking, and the wired policy knobs (audit, disable_auto_learn,
disable_global_layer, category_denylist, quarantine_ingest, recall_min_trust,
extra redaction).
"""

import json
import os
import pytest

from rainman.core import trust
from rainman.core.config import load_policy, Policy, DEFAULTS
from rainman.core.engine import RainmanEngine
from rainman.core.redact import safe_content, redact_content


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


@pytest.fixture(autouse=True)
def _no_real_org_policy(monkeypatch, tmp_path):
    # Point org policy at a non-existent file so the host's real policy
    # (and any system path) can never leak into these tests.
    monkeypatch.setenv("RAINMAN_ORG_POLICY", str(tmp_path / "nope-policy.json"))


@pytest.mark.unit
class TestPrecedence:
    def test_builtin_defaults_when_nothing_set(self, tmp_path, monkeypatch):
        p = load_policy(project_dir=str(tmp_path / "proj"), global_dir=str(tmp_path / "glob"))
        assert p.get("disable_auto_learn") == DEFAULTS["disable_auto_learn"]
        assert p.get("auto_inject_min_trust") == "hook"

    def test_project_overrides_user(self, tmp_path, monkeypatch):
        proj = str(tmp_path / "proj")
        glob = str(tmp_path / "glob")
        _write(os.path.join(proj, ".rainman", "config.json"), {"retention_days": 30})
        _write(os.path.join(glob, "config.json"), {"retention_days": 90})
        p = load_policy(project_dir=proj, global_dir=glob)
        assert p.get("retention_days") == 30

    def test_org_enforce_beats_everything_and_locks(self, tmp_path, monkeypatch):
        org = tmp_path / "policy.json"
        org.write_text(json.dumps({
            "enforce": {"disable_auto_learn": True},
            "defaults": {"retention_days": 365},
        }))
        monkeypatch.setenv("RAINMAN_ORG_POLICY", str(org))
        proj = str(tmp_path / "proj")
        _write(os.path.join(proj, ".rainman", "config.json"),
               {"disable_auto_learn": False, "retention_days": 30})
        p = load_policy(project_dir=proj, global_dir=str(tmp_path / "glob"))
        # enforce wins and is locked despite project trying to relax it
        assert p.get("disable_auto_learn") is True
        assert p.locked("disable_auto_learn") is True
        # org default is overridable by project
        assert p.get("retention_days") == 30
        assert p.locked("retention_days") is False

    def test_garbled_policy_file_ignored(self, tmp_path, monkeypatch):
        org = tmp_path / "policy.json"
        org.write_text("{ this is not json")
        monkeypatch.setenv("RAINMAN_ORG_POLICY", str(org))
        p = load_policy(project_dir=str(tmp_path / "proj"), global_dir=str(tmp_path / "glob"))
        assert p.get("disable_auto_learn") is False  # falls back to builtin


@pytest.mark.unit
class TestWiredKnobs:
    def _engine_with_project_policy(self, tmp_path, policy):
        proj = str(tmp_path / "proj")
        _write(os.path.join(proj, ".rainman", "config.json"), policy)
        return RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "glob"))

    def test_category_denylist_rejects(self, tmp_path):
        engine = self._engine_with_project_policy(tmp_path, {"category_denylist": ["failure"]})
        ok = engine.add(content="a normal note about the build", category="note")
        blocked = engine.add(content="a failure we should not store", category="failure")
        assert ok is not None
        assert blocked is None

    def test_disable_global_layer_coerces_writes(self, tmp_path):
        engine = self._engine_with_project_policy(tmp_path, {"disable_global_layer": True})
        m = engine.add(content="tried to store globally", layer="global")
        assert m.layer == "project"

    def test_quarantine_ingest_hides_from_recall(self, tmp_path):
        engine = self._engine_with_project_policy(tmp_path, {"quarantine_ingest": True})
        engine.add(content="ingested rate limit note from repo history", source="ingest:files")
        engine.add(content="user note on rate limit handling", source="cli")
        hits = engine.recall("rate limit", limit=10)
        assert hits  # user memory still found
        assert all(r.memory.trust != trust.INGEST for r in hits)

    def test_recall_min_trust_policy_default(self, tmp_path):
        engine = self._engine_with_project_policy(tmp_path, {"recall_min_trust": "hook"})
        engine.add(content="ingested note about caching from repo", source="ingest:files")
        engine.add(content="hook learned note about caching", source="hook:post_tool_use:Read")
        hits = engine.recall("caching")  # no explicit min_trust -> policy applies
        assert all(r.memory.trust != trust.INGEST for r in hits)

    def test_audit_enabled_via_policy(self, tmp_path):
        engine = self._engine_with_project_policy(tmp_path, {"audit": True})
        assert engine.audit.enabled is True


@pytest.mark.unit
class TestRedactionExtensions:
    def test_extra_pattern_redacted(self):
        out = redact_content("internal id ACME-1234567", extra_patterns=[r"ACME-\d+"])
        assert "ACME-1234567" not in out
        assert "[REDACTED]" in out

    def test_invalid_extra_pattern_ignored(self):
        # Must not raise on a bad regex
        out = redact_content("hello world", extra_patterns=["(unclosed"])
        assert out == "hello world"

    def test_extra_path_denylist_skips(self):
        assert safe_content("some content here that is long enough to keep",
                            file_path="config/topsecret.conf",
                            extra_path_denylist=["topsecret"]) is None


@pytest.mark.unit
class TestPolicyExplain:
    """`rainman policy` provenance report: effective value + which layer set it."""

    def test_builtin_provenance(self):
        p = Policy(enforce={}, project={}, user={}, org_defaults={})
        info = p.explain()["audit"]
        assert info["value"] is DEFAULTS["audit"]
        assert info["source"] == "builtin" and info["locked"] is False

    def test_layer_provenance_order(self):
        p = Policy(
            enforce={"audit": True},
            project={"audit": False, "retention_days": 30},
            user={"retention_days": 7, "disable_auto_learn": True},
            org_defaults={"disable_auto_learn": False, "quarantine_ingest": True},
        )
        rep = p.explain()
        assert rep["audit"] == {"value": True, "source": "org.enforce", "locked": True}
        assert rep["retention_days"]["source"] == "project"
        assert rep["retention_days"]["value"] == 30
        assert rep["disable_auto_learn"]["source"] == "user"
        assert rep["quarantine_ingest"]["source"] == "org.defaults"

    def test_unknown_keys_surface(self):
        # A key the org sets that this client version doesn't know must still
        # be visible to an auditor, not silently hidden.
        p = Policy(enforce={"future_knob": "x"}, project={}, user={}, org_defaults={})
        rep = p.explain()
        assert rep["future_knob"] == {"value": "x", "source": "org.enforce", "locked": True}

    def test_covers_all_builtin_keys(self):
        rep = Policy(enforce={}, project={}, user={}, org_defaults={}).explain()
        assert set(DEFAULTS).issubset(rep)
