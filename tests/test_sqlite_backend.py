"""
SQLite storage backend tests (Phase 2a)
========================================

Behavioural parity with the JSON backend, persistence across instances,
backend selection via policy, the migrate command, and no 2000-cap.
"""

import json
import os
import time
import pytest

from rainman.core.sqlite_store import SqliteStore
from rainman.core.store import MemoryStore
from rainman.core.storage import make_store, StorageBackend
from rainman.core.engine import RainmanEngine
from rainman.core.models import Memory


@pytest.fixture(autouse=True)
def _no_real_org_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("RAINMAN_ORG_POLICY", str(tmp_path / "nope.json"))


def _mem(mid, content="content for testing", layer="project", recall_count=0):
    return Memory(
        id=mid, content=content, timestamp=time.time(), importance=0.5,
        category="note", sentiment="neutral", layer=layer, recall_count=recall_count,
    )


def _store(tmp_path):
    s = SqliteStore(project_dir=str(tmp_path / "proj"), global_dir=str(tmp_path / "glob"))
    s.init_global()
    s.init_project(str(tmp_path / "proj"))
    return s


@pytest.mark.unit
class TestSqliteBackend:
    def test_satisfies_protocol(self, tmp_path):
        assert isinstance(_store(tmp_path), StorageBackend)
        assert isinstance(MemoryStore(project_dir=str(tmp_path)), StorageBackend)

    def test_save_and_load_roundtrip(self, tmp_path):
        s = _store(tmp_path)
        s.save_one(_mem("a", "first memory", layer="project"))
        s.save_one(_mem("b", "second memory", layer="global"))
        loaded = {m.id: m for m in s.load_all()}
        assert set(loaded) == {"a", "b"}
        assert loaded["a"].layer == "project"
        assert loaded["b"].layer == "global"

    def test_save_one_upserts(self, tmp_path):
        s = _store(tmp_path)
        s.save_one(_mem("a", "v1"))
        m = _mem("a", "v2")
        s.save_one(m)
        loaded = s.load_all()
        assert len(loaded) == 1
        assert loaded[0].content == "v2"

    def test_persists_across_instances(self, tmp_path):
        s = _store(tmp_path)
        s.save_one(_mem("a", "durable memory"))
        s2 = SqliteStore(project_dir=str(tmp_path / "proj"), global_dir=str(tmp_path / "glob"))
        assert any(m.id == "a" for m in s2.load_all())

    def test_update_rehearsal_stats(self, tmp_path):
        s = _store(tmp_path)
        s.save_one(_mem("a", recall_count=0))
        s.update_rehearsal_stats({"a": {"recall_count": 5, "last_recalled": 123.0}}, "project")
        m = [x for x in s.load_all() if x.id == "a"][0]
        assert m.recall_count == 5
        assert m.last_recalled == 123.0

    def test_save_all_replaces_layer(self, tmp_path):
        s = _store(tmp_path)
        s.save_all([_mem("a"), _mem("b")])
        s.save_all([_mem("a")])  # b dropped
        ids = {m.id for m in s.load_all()}
        assert ids == {"a"}

    def test_no_2000_cap(self, tmp_path):
        s = _store(tmp_path)
        s.save_all([_mem(f"m{i}") for i in range(2500)])
        assert len(s.load_all()) == 2500


@pytest.mark.unit
class TestBackendSelection:
    def test_engine_uses_sqlite_when_policy_set(self, tmp_path):
        proj = str(tmp_path / "proj")
        os.makedirs(os.path.join(proj, ".rainman"), exist_ok=True)
        with open(os.path.join(proj, ".rainman", "config.json"), "w") as f:
            json.dump({"storage_backend": "sqlite"}, f)
        engine = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "glob"))
        assert isinstance(engine.store, SqliteStore)
        m = engine.add(content="a memory stored via the sqlite backend", source="cli")
        # Fresh engine reads it back from the db.
        engine2 = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "glob"))
        assert any(x.id == m.id for x in engine2.get_all())

    def test_default_backend_is_json(self, tmp_path):
        engine = RainmanEngine(project_dir=str(tmp_path / "proj"), global_dir=str(tmp_path / "glob"))
        assert isinstance(engine.store, MemoryStore)


@pytest.mark.unit
class TestMigrate:
    def test_json_to_sqlite_roundtrip(self, tmp_path):
        root = str(tmp_path / "proj")
        glob = str(tmp_path / "glob")
        # Seed a JSON store via the engine.
        e = RainmanEngine(project_dir=root, global_dir=glob)
        e.store.init_project(root)
        e.store.init_global()
        m1 = e.add(content="first json memory to migrate over", source="cli")
        m2 = e.add(content="second json memory to migrate over", source="cli")

        # Migrate json -> sqlite at the backend level (mirrors cmd_migrate).
        src = make_store(project_dir=root, global_dir=glob, backend="json")
        dst = make_store(project_dir=root, global_dir=glob, backend="sqlite")
        dst.init_global()
        dst.init_project(root)
        dst.save_all(src.load_all())

        sqlite_ids = {m.id for m in dst.load_all()}
        assert {m1.id, m2.id} <= sqlite_ids
