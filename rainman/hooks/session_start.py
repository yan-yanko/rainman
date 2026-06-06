#!/usr/bin/env python3
"""
SessionStart Hook
==================

Fires when Claude Code starts a new session.
Outputs project context (recent + important memories) to stdout.
Claude sees this as fresh context at session start.

Register in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": "python -m rainman.hooks.session_start"
            }]
        }]
    }
}
"""

import json
import os
import sys


def main():
    # Read hook input from stdin
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        print(f"[rainman] session_start: failed to parse input: {e}", file=sys.stderr)
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())

    # Import here to keep startup fast
    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=cwd)
    results = engine.context(limit=8)

    if not results:
        sys.exit(0)

    lines = ["[Rainman] Project memory loaded:\n"]
    for i, r in enumerate(results, 1):
        m = r.memory
        line = f"  {i}. [{m.category}] {m.content[:120]}"
        if m.file_refs:
            line += f" (files: {', '.join(m.file_refs)})"
        lines.append(line)

    lines.append(
        "\nUse the `recall` tool to search for more specific knowledge. "
        "Use `remember` to save new learnings."
    )

    # Output to stdout — Claude sees this as context
    print("\n".join(lines))


if __name__ == "__main__":
    main()
