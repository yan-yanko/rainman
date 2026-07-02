#!/usr/bin/env python3
"""
SessionStart Hook — Claude Code adapter
=======================================

Thin adapter over ``rainman.integration.core``: parses Claude Code's
SessionStart payload and, for the compaction source, extracts a recent topic
from the transcript. The context building and sync-pull are host-agnostic and
live in the integration core.

Sources:
  - startup / resume: load general project context
  - compact:          re-inject topical + important memory (recovers knowledge
                      lost to compaction — the killer feature)

Register in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": "python -m rainman.hooks.session_start"}]
        }]
    }
}
An empty matcher fires on all sources (startup, resume, compact).
"""

import json
import os
import sys


def main():
    # Windows stdout defaults to cp1252, which can't encode non-ASCII context
    # (Hebrew, "→"); the resulting UnicodeEncodeError exits non-zero and Claude
    # Code surfaces it as a startup hook error. Force UTF-8 so context emits.
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()

    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        from rainman.core.log import get_logger
        get_logger("hooks.session_start").warning("failed to parse input: %s", e)
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())
    source = hook_input.get("source", "startup")

    from rainman.core.engine import RainmanEngine
    from rainman.integration import core

    engine = RainmanEngine(project_dir=cwd)

    # Best-effort pull of teammates' shared memories. Silent on any failure.
    core.auto_pull(engine)

    if source == "compact":
        topic = _extract_recent_topic(hook_input.get("transcript_path", ""))
        print(core.compaction_context(engine, topic))
    else:
        text = core.session_start_context(engine)
        if text is None:
            sys.exit(0)
        print(text)  # Claude sees this as fresh context


def _extract_recent_topic(transcript_path):
    """Build a topical query from the tail of a Claude Code transcript (JSONL).
    Transcript format is host-specific, so this parsing stays in the adapter."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
        recent = lines[-20:] if len(lines) > 20 else lines
        texts = []
        for line in recent:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = entry.get("role", "")
            if role == "assistant":
                content = entry.get("content", "")
                if isinstance(content, str):
                    texts.append(content[:200])
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            text = block.get("text", "")
                            if text:
                                texts.append(text[:200])
            message = entry.get("message", {})
            if isinstance(message, dict) and message.get("role") == "assistant":
                content = message.get("content", "")
                if isinstance(content, str):
                    texts.append(content[:200])
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            text = block.get("text", "")
                            if text:
                                texts.append(text[:200])
        if texts:
            return " ".join(texts)[-500:]
    except (OSError, IOError):
        pass
    return ""


if __name__ == "__main__":
    main()
