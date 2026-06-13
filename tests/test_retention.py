"""
Retention / TTL tests (Phase 1d)
=================================

Age-based retention prune, plus the data-safety regression that the
disable_global_layer visibility filter must not let a save wipe the global
layer.
"""

import json
import os
import time
import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.models import Memory


def _write_policy(project_dir, policy):
    path = os.path.join(project_dir, ".rainman", "config.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(policy, f)


@pytest.fixture(autouse=True)
def _no_real_org_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("RAINMAN_ORG_POLICY", str(tmp_path / "nope.json"))


@pytest.mark.unit
class TestRetention:
    def test_expired_memories_pruned_on_load(self, tmp_path):
        proj = str(tmp_path / "proj")
        glob = str(tmp_path / "glob")
        # Seed an old + a fresh memory directly via a first engine.
        e1 = RainmanEngine(project_dir=proj, global_dir=glob)
        old = e1.add(content="an old memory that should expire soon", source="cli")
        fresh = e1.add(content="a fresh memory that should survive ttl", source="cli")
        # Backdate the old memory on disk.
        mem_path = os.path.join(proj, ".rainman", "memories.json")
        with open(mem_path) as f:
            data = json.load(f)
        for d in data:
            if d["id"] == old.id:
                d["timestamp"] = time.time() - 40 * 86400
        with open(mem_path, "w") as f:
            json.dump(data, f)

        # New engine with a 30-day retention policy prunes the old one on load.
        _write_policy(proj, {"retention_days": 30})
        e2 = RainmanEngine(project_dir=proj, global_dir=glob)
        ids = {m.id for m in e2.get_all()}
        assert fresh.id in ids
        assert old.id not in ids
        # And the prune was persisted.
        with open(mem_path) as f:
            assert old.id not in {d["id"] for d in json.load(f)}

    def test_no_retention_keeps_everything(self, tmp_path):
        proj = str(tmp_path / "proj")
        e = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "glob"))
        e.add(content="memory with no retention configured at all", source="cli")
        e2 = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "glob"))
        assert len(e2.get_all()) == 1


@pytest.mark.unit
class TestGlobalLayerSafety:
    def test_forget_with_global_disabled_preserves_globals(self, tmp_path):
        """Regression: visibility-filtering the global layer must not cause a
        save to wipe global memories from disk."""
        proj = str(tmp_path / "proj")
        glob = str(tmp_path / "glob")

        # Store a global memory with no policy.
        seed = RainmanEngine(project_dir=proj, global_dir=glob)
        gmem = seed.add(content="a precious global cross-project memory", source="cli", layer="global")
        pmem = seed.add(content="a project memory to be forgotten later", source="cli")

        # Now disable the global layer and forget the project memory.
        _write_policy(proj, {"disable_global_layer": True})
        e = RainmanEngine(project_dir=proj, global_dir=glob)
        assert e.forget(pmem.id) is True

        # The global memory must still be on disk.
        gpath = os.path.join(glob, "memories.json")
        with open(gpath) as f:
            global_ids = {d["id"] for d in json.load(f)}
        assert gmem.id in global_ids
