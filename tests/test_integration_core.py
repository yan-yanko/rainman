"""Host-agnostic integration core — exercised WITHOUT any Claude Code hook.

These call rainman.integration.core directly with plain args, which is exactly
what a non-Claude host adapter (git hook, aider, an MCP host) would do. If these
pass, the automatic behaviours are genuinely host-independent.
"""

import os

import pytest

from rainman.core.engine import RainmanEngine
from rainman.integration import core


@pytest.fixture
def engine(tmp_path):
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    return e, project


@pytest.mark.unit
class TestIntegrationCore:

    def test_session_start_context_empty_is_none(self, engine):
        e, _ = engine
        assert core.session_start_context(e) is None

    def test_session_start_context_returns_text(self, engine):
        e, _ = engine
        e.add("Auth uses a custom verify function, not JWT", category="convention")
        text = core.session_start_context(e)
        assert text is not None
        assert "[Rainman]" in text
        assert "verify" in text

    def test_compaction_context_includes_topic_match(self, engine):
        e, _ = engine
        e.add("Database connection pool exhaustion caused timeouts", category="failure")
        text = core.compaction_context(e, topic_query="database timeouts")
        assert "[Rainman]" in text
        assert "connection pool" in text

    def test_learn_from_tool_stores_relative_ref(self, engine):
        e, project = engine
        abs_path = os.path.join(project, "services", "auth.py")
        core.learn_from_tool(
            e, "Edit",
            {"file_path": abs_path, "old_string": "def login(user):",
             "new_string": "def login(user, remember=False):"},
            "File edited", project,
        )
        mems = e.store.load_all()
        assert len(mems) == 1
        assert mems[0].file_refs == ["services/auth.py"]

    def test_learn_from_tool_ignores_unwatched(self, engine):
        e, project = engine
        core.learn_from_tool(e, "WebFetch", {"url": "x"}, "stuff", project)
        assert e.store.load_all() == []

    def test_recall_format_plain_and_md(self, engine, capsys):
        """--format plain/md let any tool (aider, a script) pipe recall output."""
        from rainman.cli.commands import _render_memories
        e, _ = engine
        e.add("Auth uses verify_quill_sig not JWT", category="convention",
              file_refs=["src/auth.py"])
        results = e.recall("auth")

        assert _render_memories(results, "plain") is True
        out = capsys.readouterr().out
        assert "verify_quill_sig" in out and "[convention]" not in out  # content only

        assert _render_memories(results, "md") is True
        out = capsys.readouterr().out
        assert "**[convention]**" in out and "src/auth.py" in out

        assert _render_memories(results, None) is False  # falls through to rich output

    def test_capture_learnings_mines_a_decision(self, engine):
        e, project = engine
        n = core.capture_learnings(
            e, "After debugging we decided to cache tokens in Redis for the session layer.",
            project,
        )
        assert n >= 1
        assert e.store.load_all()

    def test_learn_from_tool_respects_disable_policy(self, engine, monkeypatch):
        e, project = engine
        # Patch the policy getter so the test doesn't depend on policy internals.
        monkeypatch.setattr(e.policy, "get",
                            lambda k, d=None: True if k == "disable_auto_learn" else d)
        core.learn_from_tool(e, "Edit",
                             {"file_path": os.path.join(project, "a.py"),
                              "old_string": "x", "new_string": "y"}, "ok", project)
        assert e.store.load_all() == []


@pytest.mark.unit
class TestLearnFromCommit:
    """The host-independent git auto-learn path (a post-commit hook calls this)."""

    def test_fix_commit_becomes_solution(self, engine):
        e, project = engine
        m = core.learn_from_commit(
            e, "Fix auth: JWT tokens expired early; switched to refresh-then-compare",
            ["src/auth.py"], cwd=project)
        assert m is not None
        assert m.category == "solution"           # "fix" -> solution
        assert m.source == "hook:git:post-commit"
        assert "Commit:" in m.content

    def test_trivial_commits_are_skipped(self, engine):
        e, _ = engine
        assert core.learn_from_commit(e, "wip", []) is None          # too short + prefix
        assert core.learn_from_commit(e, "Merge branch 'main'", []) is None
        assert core.learn_from_commit(e, "typo", []) is None
        assert e.store.load_all() == []

    def test_dedup_refreshes_not_duplicates(self, engine):
        e, project = engine
        msg = "Fix billing deadlock: order ledger writes by account_id to avoid the lock cycle"
        first = core.learn_from_commit(e, msg, ["src/billing.py"], cwd=project)
        assert first is not None
        second = core.learn_from_commit(e, msg, ["src/billing.py"], cwd=project)
        assert second is None                      # deduped
        assert len(e.store.load_all()) == 1

    def test_respects_disable_policy(self, engine, monkeypatch):
        e, _ = engine
        monkeypatch.setattr(e.policy, "get",
                            lambda k, d=None: True if k == "disable_auto_learn" else d)
        assert core.learn_from_commit(e, "Fix a real and important bug here", []) is None
        assert e.store.load_all() == []
