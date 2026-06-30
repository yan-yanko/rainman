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
import re
import sys


# Only auto-learn from these tools
WATCHED_TOOLS = {"Read", "Edit", "Write", "Bash"}

# Minimum content length to bother recording
MIN_CONTENT_LENGTH = 50

# Bash commands whose pass/fail outcome is worth capturing as experience.
BASH_OUTCOME_KEYWORDS = ("pytest", "test", "build", "deploy", "migrate")


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
    from rainman.core.redact import safe_content
    from rainman.core.salience import is_salient, salience_score

    engine = RainmanEngine(project_dir=cwd)

    # Org policy: auto-learn can be disabled entirely.
    if engine.policy.get("disable_auto_learn"):
        sys.exit(0)

    # Bash gets dedicated experience-card handling: a failure becomes an OPEN
    # card, and a later success on the same files RESOLVES it into a paired
    # problem/fix card. This is the typed-causal write path, not a flat note.
    if tool_name == "Bash":
        _handle_bash(engine, tool_input.get("command", ""), tool_output, cwd)
        sys.exit(0)

    # Read/Edit -> note captures.
    learning = _extract_learning(tool_name, tool_input, tool_output)
    if not learning:
        sys.exit(0)

    content, category, file_refs = learning
    # Keep stored refs project-relative (portable + no absolute-path leak).
    file_refs = [_project_relative(f, cwd) for f in file_refs]

    if len(content) < MIN_CONTENT_LENGTH:
        sys.exit(0)

    # Salience gate (M6): don't store low-signal "read file X" noise. A note must
    # carry an error / security / config / intent signal to earn a slot.
    score = salience_score(category, content, file_refs)
    if not is_salient(category, content, file_refs):
        sys.exit(0)

    # Redact secrets before storing (built-in rules + org-policy additions).
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
        metadata={"salience": round(score, 2)},
    )

    # Silent — no stdout output (don't clutter Claude's context)
    sys.exit(0)


def _paths_in_command(command: str) -> list:
    """Extract file/path-ish tokens from a shell command (for failure->fix
    pairing on overlapping files). Skips flags; keeps tokens with a path
    separator or a file extension."""
    out, seen = [], set()
    for tok in command.split():
        if tok.startswith("-"):
            continue
        if "/" in tok or re.search(r"\.\w{1,5}$", tok):
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out[:20]


def _handle_bash(engine, command: str, tool_output, cwd=None) -> None:
    """Capture Bash test/build outcomes as typed-causal experience cards."""
    if not command:
        return
    if not any(kw in command.lower() for kw in BASH_OUTCOME_KEYWORDS):
        return

    from rainman.core.redact import safe_content
    from rainman.core.salience import is_salient, salience_score

    output_str = _coerce_output(tool_output)[:1000]
    lowered = output_str.lower()
    failed = "failed" in lowered or "error" in lowered
    passed = "passed" in lowered or "success" in lowered
    file_refs = [_project_relative(p, cwd) for p in _paths_in_command(command)] \
        if cwd else _paths_in_command(command)

    if failed:
        problem = f"{command[:120]} — {output_str[:300]}"
        safe = safe_content(
            problem,
            extra_patterns=engine.policy.get("extra_redaction_patterns"),
        )
        if safe is None:
            return
        engine.record_failure(
            problem=safe, command=command, file_refs=file_refs,
            source="hook:post_tool_use:Bash",
        )
        return

    if passed:
        # Did this success resolve an open failure on the same files? If so,
        # pair them into a problem/fix card instead of a standalone note.
        open_failure = engine.find_open_failure(file_refs)
        if open_failure is not None:
            engine.resolve_failure(
                open_failure,
                fix=f"{command[:120]} now passes",
                source="hook:post_tool_use:Bash",
            )
            return
        content = f"Command succeeded: {command[:120]}"
        if is_salient("note", content, file_refs, command):
            engine.add(
                content=content, category="note", file_refs=file_refs,
                source="hook:post_tool_use:Bash", layer="project",
                metadata={"salience": round(
                    salience_score("note", content, file_refs, command), 2)},
            )


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

    # Bash is handled separately by _handle_bash (typed-causal experience cards).
    return None


def _short_path(path):
    """Shorten a file path for display."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return path


def _project_relative(path, root):
    """Store file refs relative to the project root.

    Auto-learn captures absolute tool paths (e.g.
    ``C:\\Users\\me\\proj\\rainman\\core\\store.py``). Stored verbatim those
    leak the local username/path layout when the project layer is committed,
    and don't match on another machine. Rewriting to a repo-relative POSIX path
    (``rainman/core/store.py``) keeps memories portable. Paths outside the
    project tree are left as-is rather than emitting a ``..`` ladder.
    """
    if not path:
        return path
    try:
        rel = os.path.relpath(path, root)
    except (ValueError, OSError):
        return path  # e.g. different drive on Windows
    if rel.startswith("..") or os.path.isabs(rel):
        return path
    return rel.replace("\\", "/")


if __name__ == "__main__":
    main()
