"""Hook tests — synthetic JSON stdin, malformed JSON handling."""

import json
import os
import subprocess
import sys
import pytest


PYTHON = sys.executable


@pytest.fixture
def project_dir(tmp_path):
    """Create a project with initialized .rainman/ directory."""
    project = str(tmp_path / "project")
    os.makedirs(project)
    rainman_dir = os.path.join(project, ".rainman")
    os.makedirs(rainman_dir)
    # Create empty memories.json
    with open(os.path.join(rainman_dir, "memories.json"), "w") as f:
        json.dump([], f)
    # Create config.json
    with open(os.path.join(rainman_dir, "config.json"), "w") as f:
        json.dump({"version": "0.1.0"}, f)
    # Init global too
    global_dir = str(tmp_path / "global_rainman")
    os.makedirs(global_dir)
    with open(os.path.join(global_dir, "memories.json"), "w") as f:
        json.dump([], f)
    return project, global_dir


def _run_hook(module, stdin_data, cwd, env_extra=None):
    """Run a hook module via subprocess with given stdin, isolated from real ~/.rainman/."""
    env = os.environ.copy()
    # Isolate from real ~/.rainman/ — use subdir so global != project
    fakehome = os.path.join(cwd, "_fakehome")
    os.makedirs(fakehome, exist_ok=True)
    env["USERPROFILE"] = fakehome
    env["HOME"] = fakehome
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [PYTHON, "-m", module],
        input=json.dumps(stdin_data) if isinstance(stdin_data, dict) else stdin_data,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=30,
    )
    return result


def _load_memories(project_dir):
    """Load memories from project's .rainman/memories.json."""
    path = os.path.join(project_dir, ".rainman", "memories.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.unit
class TestPostToolUse:
    """post_tool_use hook — auto-learn from tool usage."""

    def test_read_creates_memory(self, project_dir):
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Read",
            "cwd": project,
            "tool_input": {"file_path": "services/api/auth.py"},
            "tool_output": "class PaymentServiceController:\n    def process_payment(self, amount, currency):\n        # Uses Redis cache for session tokens\n        pass\n" * 5,
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 1
        assert "auth.py" in memories[0]["content"]

    def test_edit_creates_memory(self, project_dir):
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Edit",
            "cwd": project,
            "tool_input": {
                "file_path": "services/auth.py",
                "old_string": "def login(user):",
                "new_string": "def login(user, remember=False):",
            },
            "tool_output": "File edited successfully",
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 1
        assert "Edited" in memories[0]["content"]

    def test_bash_test_failure_creates_memory(self, project_dir):
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Bash",
            "cwd": project,
            "tool_input": {"command": "pytest tests/test_auth.py tests/test_login.py -x --verbose"},
            # Note: output must NOT contain "passed" — hook checks passed before failed
            "tool_output": "FAILED tests/test_auth.py::test_login_with_expired_token - AssertionError: expected 200 got 401 for user auth endpoint\n1 failed in 2.34s",
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 1
        assert memories[0]["category"] == "failure"

    def test_bash_test_success_creates_memory(self, project_dir):
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Bash",
            "cwd": project,
            "tool_input": {"command": "pytest tests/test_auth.py tests/test_login.py tests/test_session.py -q --verbose"},
            "tool_output": "6 passed in 0.08s. All tests passed successfully. No warnings.",
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 1
        assert "succeeded" in memories[0]["content"].lower()

    def test_unwatched_tool_ignored(self, project_dir):
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "WebSearch",
            "cwd": project,
            "tool_input": {"query": "python async patterns"},
            "tool_output": "Search results...",
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 0

    def test_short_content_ignored(self, project_dir):
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Read",
            "cwd": project,
            "tool_input": {"file_path": "tiny.txt"},
            "tool_output": "hi",
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 0

    def test_dedup_same_file_twice(self, project_dir):
        """Reading the same file twice should NOT create duplicate memories."""
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Read",
            "cwd": project,
            "tool_input": {"file_path": "services/api/auth.py"},
            "tool_output": "class PaymentServiceController:\n    def process_payment(self, amount, currency):\n        pass\n" * 5,
        }
        # First call
        _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        # Second call — same file
        _run_hook("rainman.hooks.post_tool_use", hook_input, project)

        memories = _load_memories(project)
        assert len(memories) == 1  # Dedup should prevent second entry

    def test_malformed_json_exits_cleanly(self, project_dir):
        project, global_dir = project_dir
        result = _run_hook("rainman.hooks.post_tool_use", "not valid json {{{", project)
        assert result.returncode == 0
        assert "failed to parse" in result.stderr.lower()


@pytest.mark.unit
class TestSessionStart:
    """session_start hook — outputs context to stdout."""

    def test_empty_store_no_output(self, project_dir):
        project, global_dir = project_dir
        hook_input = {"cwd": project}
        result = _run_hook("rainman.hooks.session_start", hook_input, project)
        assert result.returncode == 0
        # No memories -> no stdout output (silent exit)
        assert result.stdout.strip() == ""

    def test_with_memories_outputs_context(self, project_dir):
        """Pre-populate memories, then run session_start — should output them."""
        project, global_dir = project_dir
        import time
        memories = [{
            "id": "rm_test_001",
            "content": "auth.py handles JWT token refresh",
            "timestamp": time.time(),
            "importance": 0.8,
            "category": "pattern",
            "sentiment": "neutral",
            "linked_ids": [],
            "recall_count": 0,
            "last_recalled": None,
            "tags": ["api"],
            "source": "cli",
            "file_refs": ["services/api/auth.py"],
            "layer": "project",
            "metadata": {},
        }]
        path = os.path.join(project, ".rainman", "memories.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memories, f)

        hook_input = {"cwd": project}
        result = _run_hook("rainman.hooks.session_start", hook_input, project)
        assert result.returncode == 0
        assert "[Rainman]" in result.stdout
        assert "auth" in result.stdout

    def test_malformed_json_exits_cleanly(self, project_dir):
        project, global_dir = project_dir
        result = _run_hook("rainman.hooks.session_start", "{{broken", project)
        assert result.returncode == 0


@pytest.mark.unit
class TestPostCompact:
    """post_compact hook — re-injects memories after context compaction."""

    def test_with_summary_outputs_context(self, project_dir):
        """Pre-populate, then run post_compact with a summary."""
        project, global_dir = project_dir
        import time
        memories = [{
            "id": "rm_test_002",
            "content": "payment service has race condition in rate limiter",
            "timestamp": time.time(),
            "importance": 0.9,
            "category": "failure",
            "sentiment": "negative",
            "linked_ids": [],
            "recall_count": 2,
            "last_recalled": time.time(),
            "tags": ["api", "bug"],
            "source": "cli",
            "file_refs": [],
            "layer": "project",
            "metadata": {},
        }]
        path = os.path.join(project, ".rainman", "memories.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memories, f)

        hook_input = {
            "cwd": project,
            "summary": "Working on payment service rate-limit bug",
        }
        result = _run_hook("rainman.hooks.post_compact", hook_input, project)
        assert result.returncode == 0
        assert "[Rainman]" in result.stdout
        assert "rate" in result.stdout.lower() or "payment" in result.stdout.lower()

    def test_malformed_json_exits_cleanly(self, project_dir):
        project, global_dir = project_dir
        result = _run_hook("rainman.hooks.post_compact", "not json!", project)
        assert result.returncode == 0
