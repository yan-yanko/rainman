#!/usr/bin/env python3
"""
PostToolUse Hook — Auto-Learn
===============================

Fires after Claude uses a tool (Read, Edit, Bash, etc.).
Silently records learnings from tool usage:
- File reads → remember what the file contains
- Bug fixes → remember the fix
- Test runs → remember what passed/failed

Register in .claude/settings.json:
{
    "hooks": {
        "PostToolUse": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": "python -m rainman.hooks.post_tool_use"
            }]
        }]
    }
}
"""

import json
import os
import sys


# Only auto-learn from these tools
WATCHED_TOOLS = {"Read", "Edit", "Write", "Bash"}

# Minimum content length to bother recording
MIN_CONTENT_LENGTH = 50


def _coerce_output(resp) -> str:
    """Normalize a PostToolUse tool result into searchable text.

    Claude Code delivers the result as a string for some tools and a dict for
    others (e.g. Bash → {"stdout", "stderr", ...}). Flatten either into text so
    the learning extractors can scan it.
    """
    if not resp:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for key in ("stdout", "output", "content", "result", "text", "stderr"):
            val = resp.get(key)
            if val:
                return str(val)
        return " ".join(str(v) for v in resp.values() if v)
    if isinstance(resp, (list, tuple)):
        return "\n".join(_coerce_output(x) for x in resp)
    return str(resp)


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        from rainman.core.log import get_logger
        get_logger("hooks.post_tool_use").warning("failed to parse input: %s", e)
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name not in WATCHED_TOOLS:
        sys.exit(0)

    cwd = hook_input.get("cwd", os.getcwd())
    tool_input = hook_input.get("tool_input", {})
    # Claude Code's PostToolUse payload carries the result under "tool_response".
    # Fall back to the legacy "tool_output" key for older/compat payloads.
    raw_output = hook_input.get("tool_response")
    if raw_output is None:
        raw_output = hook_input.get("tool_output", "")
    tool_output = _coerce_output(raw_output)

    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=cwd)

    # Org policy: auto-learn can be disabled entirely.
    if engine.policy.get("disable_auto_learn"):
        sys.exit(0)

    # Extract learning based on tool type
    learning = _extract_learning(tool_name, tool_input, tool_output)
    if not learning:
        sys.exit(0)

    content, category, file_refs = learning

    if len(content) < MIN_CONTENT_LENGTH:
        sys.exit(0)

    # Redact secrets before storing (built-in rules + org-policy additions).
    from rainman.core.redact import safe_content

    safe = safe_content(
        content,
        file_path=file_refs[0] if file_refs else None,
        extra_patterns=engine.policy.get("extra_redaction_patterns"),
        extra_path_denylist=engine.policy.get("path_denylist"),
    )
    if safe is None:
        sys.exit(0)  # Sensitive file or content too redacted to be useful
    content = safe

    # Dedup: refresh existing memory instead of creating duplicate
    if file_refs:
        existing = engine.links(file_refs[0])
        for m in existing:
            if m.source and m.source.startswith(f"hook:post_tool_use:{tool_name}"):
                engine.refresh(m.id)
                sys.exit(0)

    engine.add(
        content=content,
        category=category,
        file_refs=file_refs,
        source=f"hook:post_tool_use:{tool_name}",
        layer="project",
    )

    # Silent — no stdout output (don't clutter Claude's context)
    sys.exit(0)


def _extract_learning(tool_name, tool_input, tool_output):
    """Extract a learning from tool usage. Returns (content, category, file_refs) or None."""

    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return None
        # Record that this file was read and a brief summary
        # Only record if the output is substantial
        output_str = str(tool_output)[:500] if tool_output else ""
        if len(output_str) < MIN_CONTENT_LENGTH:
            return None
        # Extract first meaningful line as summary
        lines = [ln.strip() for ln in output_str.split("\n") if ln.strip() and not ln.strip().startswith("#")]
        summary = lines[0][:150] if lines else "file contents"
        return (
            f"File {_short_path(file_path)}: {summary}",
            "note",
            [file_path],
        )

    elif tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        old_string = tool_input.get("old_string", "")[:100]
        new_string = tool_input.get("new_string", "")[:100]
        if not file_path:
            return None
        return (
            f"Edited {_short_path(file_path)}: changed '{old_string}' to '{new_string}'",
            "note",
            [file_path],
        )

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        output_str = str(tool_output)[:300] if tool_output else ""

        # Only record test runs, builds, and significant commands
        if any(kw in command for kw in ["pytest", "test", "build", "deploy", "migrate"]):
            failed = "failed" in output_str.lower() or "error" in output_str.lower()
            passed = "passed" in output_str.lower() or "success" in output_str.lower()
            # Check failure first — "30 failed, 100 passed" contains both words
            if failed:
                return (f"Command failed: {command[:100]} — {output_str[:150]}", "failure", [])
            elif passed:
                return (f"Command succeeded: {command[:100]}", "note", [])

    return None


def _short_path(path):
    """Shorten a file path for display."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return path


if __name__ == "__main__":
    main()
