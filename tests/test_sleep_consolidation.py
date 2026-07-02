"""Memory typing + the offline 'sleep' pass (episodic->semantic + forgetting).

Grounds Rainman's new cognitive-memory features against the research map:
- episodic vs semantic vs procedural typing (Squire/Tulving taxonomy)
- extracting common elements across recurring events (Squire operating principle)
- functional/adaptive forgetting of un-rehearsed low-value traces (Ebbinghaus)
"""

import os

import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.models import Memory
from rainman.core import consolidate as C


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


def _mem(**kw):
    base = dict(id="m", content="x", timestamp=0.0, importance=0.5, category="note")
    base.update(kw)
    return Memory(**base)


@pytest.mark.unit
class TestMemoryType:

    def test_episodic_from_experience_or_anchored_event(self):
        assert _mem(category="failure", file_refs=["src/a.py"]).memory_type == "episodic"
        assert _mem(category="solution", file_refs=["src/a.py"]).memory_type == "episodic"
        assert _mem(category="note", metadata={"experience": {}}).memory_type == "episodic"

    def test_procedural_from_rule_categories(self):
        assert _mem(category="convention").memory_type == "procedural"
        assert _mem(category="pattern").memory_type == "procedural"

    def test_semantic_default_and_consolidated(self):
        assert _mem(category="note").memory_type == "semantic"
        assert _mem(category="decision").memory_type == "semantic"
        # A failure with NO place anchor is a context-free lesson -> semantic.
        assert _mem(category="failure", file_refs=[]).memory_type == "semantic"
        # A consolidated generalization is semantic regardless of category.
        assert _mem(category="pattern", metadata={"consolidated": True}).memory_type == "semantic"


@pytest.mark.unit
class TestConsolidation:

    def _seed_recurring(self, e):
        # Three episodic failures sharing distinctive terms + a file.
        for i in range(3):
            e.add(f"The bulk job deadlocked on the ledger table under concurrency (run {i})",
                  category="failure", file_refs=["src/ledger.py"],
                  source="hook:post_tool_use:Bash")

    def test_promotes_recurring_episodics_to_semantic(self, engine):
        self._seed_recurring(engine)
        report = engine.consolidate(forget=False)
        assert report["n_promoted"] >= 1

        gens = [m for m in engine.get_all()
                if m.metadata.get("consolidated")]
        assert len(gens) == 1
        gen = gens[0]
        assert gen.memory_type == "semantic"        # abstraction is semantic
        assert "ledger" in " ".join(gen.metadata["terms"]) or "deadlock" in " ".join(gen.metadata["terms"])
        assert len(gen.metadata["consolidated_from"]) == 3
        # Source events now link to the generalization (no longer orphans).
        events = [m for m in engine.get_all() if m.metadata.get("consolidated_into") == gen.id]
        assert len(events) == 3

    def test_consolidation_is_idempotent(self, engine):
        self._seed_recurring(engine)
        assert engine.consolidate(forget=False)["n_promoted"] >= 1
        # Second pass: the events are marked, nothing new to promote.
        assert engine.consolidate(forget=False)["n_promoted"] == 0

    def test_dry_run_writes_nothing(self, engine):
        self._seed_recurring(engine)
        before = len(engine.get_all())
        report = engine.consolidate(dry_run=True)
        assert report["n_promoted"] >= 1
        assert len(engine.get_all()) == before   # no new generalization persisted

    def test_no_clusters_when_events_unrelated(self, engine):
        engine.add("Fixed the CSS dark-mode flash", category="solution", file_refs=["ui/theme.css"])
        engine.add("Rotated the signing key", category="failure", file_refs=["ops/keys.md"])
        engine.add("Rate limiter dropped valid requests", category="failure", file_refs=["api/gw.py"])
        assert engine.consolidate(forget=False)["n_promoted"] == 0


@pytest.mark.unit
class TestFunctionalForgetting:

    def test_forgets_only_stale_orphan_auto_learned(self):
        now = 1_000_000.0
        old = now - 40 * 86400
        mems = [
            # forgettable: old, never recalled, low importance, orphan, auto-learned
            _mem(id="stale", timestamp=old, importance=0.2, recall_count=0,
                 source="hook:post_tool_use:Read", linked_ids=[]),
            # spared: user-authored knowledge
            _mem(id="user", timestamp=old, importance=0.2, source="cli"),
            # spared: has been recalled (rehearsed)
            _mem(id="recalled", timestamp=old, importance=0.2, recall_count=3,
                 source="hook:post_tool_use:Read"),
            # spared: recent
            _mem(id="recent", timestamp=now, importance=0.2, source="hook:post_tool_use:Read"),
            # spared: important
            _mem(id="important", timestamp=old, importance=0.9, source="hook:post_tool_use:Read"),
            # spared: linked (references another id, so it's not an orphan itself)
            _mem(id="linked", timestamp=old, importance=0.2, source="hook:post_tool_use:Read",
                 linked_ids=["user"]),
        ]
        drop = C.forgettable(mems, now)
        assert drop == ["stale"]

    def test_spares_experience_cards_and_generalizations(self):
        now = 1_000_000.0
        old = now - 90 * 86400
        mems = [
            _mem(id="card", timestamp=old, importance=0.2, source="hook:post_tool_use:Bash",
                 metadata={"experience": {"problem": "x"}}),
            _mem(id="gen", timestamp=old, importance=0.2, source="hook:consolidation",
                 metadata={"consolidated": True}),
        ]
        assert C.forgettable(mems, now) == []

    def test_engine_consolidate_forgets_via_pass(self, tmp_path):
        project = str(tmp_path / "p")
        global_dir = str(tmp_path / "g")
        os.makedirs(project)
        os.makedirs(global_dir)
        e = RainmanEngine(project_dir=project, global_dir=global_dir)
        e.store.init_project(project)
        e.store.init_global()
        # An old orphan auto-learned note, forced stale.
        m = e.add("read some boring file once", category="note",
                  source="hook:post_tool_use:Read")
        m.timestamp = 1.0            # ancient
        m.importance = 0.2
        e.store.save_all(e.get_all())
        report = e.consolidate(forget=True)
        assert m.id in report["forgotten"]
        assert all(x.id != m.id for x in e.get_all())
