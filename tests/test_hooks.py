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


def _run_hook(module, stdin_data, cwd, env_extra=None, capture_encoding=None):
    """Run a hook module via subprocess with given stdin, isolated from real ~/.rainman/.

    ``capture_encoding`` forces how the parent decodes the child's output; pass
    "utf-8" when the child may emit non-ASCII so the test itself can't choke on
    it (used alongside env PYTHONIOENCODING to simulate a legacy stdout codec).
    """
    env = os.environ.copy()
    # Isolate from real ~/.rainman/ — use subdir so global != project
    fakehome = os.path.join(cwd, "_fakehome")
    os.makedirs(fakehome, exist_ok=True)
    env["USERPROFILE"] = fakehome
    env["HOME"] = fakehome
    if env_extra:
        env.update(env_extra)
    extra = {"encoding": capture_encoding, "errors": "replace"} if capture_encoding else {}
    result = subprocess.run(
        [PYTHON, "-m", module],
        input=json.dumps(stdin_data) if isinstance(stdin_data, dict) else stdin_data,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=30,
        **extra,
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
            "tool_response": "class PaymentServiceController:\n    def process_payment(self, amount, currency):\n        # Uses Redis cache for session tokens\n        pass\n" * 5,
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
            "tool_response": "FAILED tests/test_auth.py::test_login_with_expired_token - AssertionError: expected 200 got 401 for user auth endpoint\n1 failed in 2.34s",
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
            "tool_response": "6 passed in 0.08s. All tests passed successfully. No warnings.",
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
            "tool_response": "class PaymentServiceController:\n    def process_payment(self, amount, currency):\n        pass\n" * 5,
        }
        # First call
        _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        # Second call — same file
        _run_hook("rainman.hooks.post_tool_use", hook_input, project)

        memories = _load_memories(project)
        assert len(memories) == 1  # Dedup should prevent second entry

    def test_boring_read_is_not_stored(self, project_dir):
        """M6: a substantial-but-low-signal file read is dropped, not stored."""
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Read",
            "cwd": project,
            "tool_input": {"file_path": "utils/formatting.py"},
            "tool_response": "def to_title_case(text):\n    return text.title()\n\ndef pad(text, n):\n    return text.ljust(n)\n" * 4,
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0
        assert _load_memories(project) == []

    def test_bash_failure_then_pass_pairs_into_fix(self, project_dir):
        """M1: a failing test run, then a passing run on the same file, get
        paired into a resolved problem/fix experience card."""
        project, global_dir = project_dir
        fail = {
            "tool_name": "Bash",
            "cwd": project,
            "tool_input": {"command": "pytest tests/test_auth.py -x"},
            "tool_response": "FAILED tests/test_auth.py::test_login - AssertionError: expected 200 got 401\n1 failed in 1.2s",
        }
        _run_hook("rainman.hooks.post_tool_use", fail, project)
        after_fail = _load_memories(project)
        assert len(after_fail) == 1
        assert after_fail[0]["category"] == "failure"
        assert after_fail[0]["metadata"]["experience"]["outcome"] == "open"

        passing = {
            "tool_name": "Bash",
            "cwd": project,
            "tool_input": {"command": "pytest tests/test_auth.py -x"},
            "tool_response": "1 passed in 1.1s",
        }
        _run_hook("rainman.hooks.post_tool_use", passing, project)
        after_pass = _load_memories(project)

        # The failure was resolved + a linked solution card was created.
        by_cat = {m["category"]: m for m in after_pass}
        assert "failure" in by_cat and "solution" in by_cat
        failure = by_cat["failure"]
        solution = by_cat["solution"]
        assert failure["metadata"]["experience"]["outcome"] == "resolved"
        assert solution["metadata"]["experience"]["resolved_failure"] == failure["id"]
        assert solution["id"] in failure["linked_ids"]

    def test_legacy_tool_output_fallback(self, project_dir):
        """Older payloads used 'tool_output'; the hook must still read it."""
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Bash",
            "cwd": project,
            "tool_input": {"command": "pytest tests/test_legacy.py -q"},
            "tool_output": "FAILED tests/test_legacy.py::test_thing - boom in the parser\n1 failed in 0.5s",
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0
        memories = _load_memories(project)
        assert len(memories) == 1
        assert memories[0]["category"] == "failure"

    def test_dict_tool_response_coerced(self, project_dir):
        """Claude Code delivers some results as a dict (e.g. Bash stdout/stderr);
        the hook must flatten it to text, not stringify the whole dict away."""
        project, global_dir = project_dir
        hook_input = {
            "tool_name": "Bash",
            "cwd": project,
            "tool_input": {"command": "pytest tests/test_api.py tests/test_payments.py tests/test_users.py -q"},
            "tool_response": {
                "stdout": "12 passed in 1.2s. all checks succeeded cleanly",
                "stderr": "",
            },
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0
        memories = _load_memories(project)
        assert len(memories) == 1
        assert "succeeded" in memories[0]["content"].lower()

    def test_malformed_json_exits_cleanly(self, project_dir):
        project, global_dir = project_dir
        result = _run_hook("rainman.hooks.post_tool_use", "not valid json {{{", project)
        assert result.returncode == 0
        assert "failed to parse" in result.stderr.lower()

    def test_absolute_file_ref_stored_relative(self, project_dir):
        """Auto-learn must store project-relative refs, not absolute local paths
        (portable across machines + no username/path leak when committed)."""
        project, global_dir = project_dir
        abs_path = os.path.join(project, "services", "auth.py")
        hook_input = {
            "tool_name": "Edit",
            "cwd": project,
            "tool_input": {
                "file_path": abs_path,
                "old_string": "def login(user):",
                "new_string": "def login(user, remember=False):",
            },
            "tool_output": "File edited successfully",
        }
        result = _run_hook("rainman.hooks.post_tool_use", hook_input, project)
        assert result.returncode == 0
        memories = _load_memories(project)
        assert len(memories) == 1
        assert memories[0]["file_refs"] == ["services/auth.py"]
        assert project not in memories[0]["file_refs"][0]


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

    def test_non_ascii_content_does_not_crash_on_legacy_codec(self, project_dir):
        """Regression: Hebrew/non-ASCII memory content used to crash the hook on
        a cp1252 stdout (Windows default) with UnicodeEncodeError, surfaced as a
        startup hook error and dropping all injected context. Forcing the child
        to cp1252 reproduces it on any platform; the UTF-8 fix must survive it."""
        project, global_dir = project_dir
        import time
        memories = [{
            "id": "rm_test_he",
            "content": "האימות נכשל כי הטוקן פג תוקף → צריך לרענן את הטוקן",
            "timestamp": time.time(),
            "importance": 0.9,
            "category": "solution",
            "sentiment": "neutral",
            "linked_ids": [],
            "recall_count": 0,
            "last_recalled": None,
            "tags": [],
            "source": "cli",
            "file_refs": [],
            "layer": "project",
            "metadata": {},
        }]
        path = os.path.join(project, ".rainman", "memories.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memories, f, ensure_ascii=False)

        result = _run_hook(
            "rainman.hooks.session_start", {"cwd": project}, project,
            env_extra={"PYTHONIOENCODING": "cp1252"},
            capture_encoding="utf-8",
        )
        assert result.returncode == 0
        assert "[Rainman]" in result.stdout


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


def _create_transcript(path, entries):
    """Create a JSONL transcript file with given entries."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_transcript_entries(assistant_texts, padding=True):
    """Build transcript JSONL entries from assistant text strings.
    Adds padding user messages to meet the MIN_TRANSCRIPT_LINES threshold."""
    entries = []
    for text in assistant_texts:
        entries.append({"role": "user", "content": "continue"})
        entries.append({"role": "assistant", "content": text})
    if padding:
        # Pad to >= 10 lines
        while len(entries) < 12:
            entries.append({"role": "user", "content": "ok"})
            entries.append({"role": "assistant", "content": "Acknowledged."})
    return entries


@pytest.mark.unit
class TestSessionEnd:
    """session_end hook — captures key decisions from transcripts."""

    def test_extracts_decisions(self, project_dir):
        project, global_dir = project_dir
        transcript_path = os.path.join(project, "transcript.jsonl")
        entries = _make_transcript_entries([
            "After reviewing the options, we decided to use Redis for caching because it supports TTL natively and has good Python bindings.",
            "The fix is to add a retry mechanism with exponential backoff in the API client layer.",
            "Just checking the status of the build.",
        ])
        _create_transcript(transcript_path, entries)

        hook_input = {
            "cwd": project,
            "reason": "logout",
            "transcript_path": transcript_path,
        }
        result = _run_hook("rainman.hooks.session_end", hook_input, project)
        assert result.returncode == 0
        assert result.stdout.strip() == ""  # Silent hook

        memories = _load_memories(project)
        assert len(memories) >= 1
        # Should capture the decision and/or the fix
        contents = " ".join(m["content"] for m in memories)
        assert "decided to" in contents.lower() or "fix is" in contents.lower()

    def test_skips_short_sessions(self, project_dir):
        project, global_dir = project_dir
        transcript_path = os.path.join(project, "transcript.jsonl")
        entries = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        _create_transcript(transcript_path, entries)

        hook_input = {
            "cwd": project,
            "reason": "logout",
            "transcript_path": transcript_path,
        }
        result = _run_hook("rainman.hooks.session_end", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 0

    def test_skips_clear_reason(self, project_dir):
        project, global_dir = project_dir
        transcript_path = os.path.join(project, "transcript.jsonl")
        entries = _make_transcript_entries([
            "We decided to rewrite the entire auth module using JWT tokens.",
        ])
        _create_transcript(transcript_path, entries)

        hook_input = {
            "cwd": project,
            "reason": "clear",
            "transcript_path": transcript_path,
        }
        result = _run_hook("rainman.hooks.session_end", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 0

    def test_missing_transcript_exits_cleanly(self, project_dir):
        project, global_dir = project_dir
        hook_input = {
            "cwd": project,
            "reason": "logout",
            # No transcript_path
        }
        result = _run_hook("rainman.hooks.session_end", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) == 0

    def test_malformed_json_exits_cleanly(self, project_dir):
        project, global_dir = project_dir
        result = _run_hook("rainman.hooks.session_end", "not valid json {{{", project)
        assert result.returncode == 0
        assert "failed to parse" in result.stderr.lower()

    def test_caps_at_5_memories(self, project_dir):
        project, global_dir = project_dir
        transcript_path = os.path.join(project, "transcript.jsonl")
        # Create many distinct decisions spread across the transcript
        texts = [
            f"We decided to use approach_{i} for the module_{i} component because it handles edge cases better and provides cleaner separation of concerns."
            for i in range(15)
        ]
        entries = _make_transcript_entries(texts)
        _create_transcript(transcript_path, entries)

        hook_input = {
            "cwd": project,
            "reason": "logout",
            "transcript_path": transcript_path,
        }
        result = _run_hook("rainman.hooks.session_end", hook_input, project)
        assert result.returncode == 0

        memories = _load_memories(project)
        assert len(memories) <= 5
