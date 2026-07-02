#!/usr/bin/env python3
"""
PostToolUse Hook — Claude Code adapter
======================================

Thin adapter: parses Claude Code's PostToolUse stdin payload and delegates to
the host-agnostic ``rainman.integration.core.learn_from_tool``. All the learning
logic (salience gate, secret redaction, relative file paths, failure→fix
pairing) lives in the integration core so other hosts can reuse it.

Register in .claude/settings.json:
{
    "hooks": {
        "PostToolUse": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": "python -m rainman.hooks.post_tool_use"}]
        }]
    }
}
"""

import json
import os
import sys


def main():
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()

    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        from rainman.core.log import get_logger
        get_logger("hooks.post_tool_use").warning("failed to parse input: %s", e)
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    cwd = hook_input.get("cwd", os.getcwd())
    tool_input = hook_input.get("tool_input", {})
    # Claude Code delivers the result under "tool_response"; fall back to the
    # legacy "tool_output" key for older/compat payloads.
    raw_output = hook_input.get("tool_response")
    if raw_output is None:
        raw_output = hook_input.get("tool_output", "")

    from rainman.core.engine import RainmanEngine
    from rainman.integration import core

    engine = RainmanEngine(project_dir=cwd)
    core.learn_from_tool(engine, tool_name, tool_input,
                         core._coerce_output(raw_output), cwd)

    # Silent — no stdout (don't clutter the host's context).
    sys.exit(0)


if __name__ == "__main__":
    main()
