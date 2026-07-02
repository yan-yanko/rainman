#!/usr/bin/env python3
"""
SessionEnd Hook — Claude Code adapter
=====================================

Thin adapter: reads Claude Code's session transcript (JSONL), extracts the
assistant text, and delegates to ``rainman.integration.core.capture_learnings``
(keyword-based decision/pattern/failure mining, zero LLM, secret-redacted). The
mining logic is host-agnostic; only the transcript parsing is Claude-specific.

Register in .claude/settings.json:
{
    "hooks": {
        "SessionEnd": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": "python -m rainman.hooks.session_end"}]
        }]
    }
}
"""

import json
import os
import sys

# Minimum transcript lines to bother processing.
MIN_TRANSCRIPT_LINES = 10


def main():
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()

    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        from rainman.core.log import get_logger
        get_logger("hooks.session_end").warning("failed to parse input: %s", e)
        sys.exit(0)

    if hook_input.get("reason", "") == "clear":
        sys.exit(0)

    cwd = hook_input.get("cwd", os.getcwd())
    transcript_path = hook_input.get("transcript_path", "")
    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    lines = _read_transcript(transcript_path)
    if len(lines) < MIN_TRANSCRIPT_LINES:
        sys.exit(0)

    assistant_text = _extract_assistant_text(lines)
    if not assistant_text:
        sys.exit(0)

    from rainman.core.engine import RainmanEngine
    from rainman.integration import core

    engine = RainmanEngine(project_dir=cwd)
    core.capture_learnings(engine, assistant_text, cwd)

    # Silent — session is ending, no context to inject.
    sys.exit(0)


def _read_transcript(path):
    """Read a JSONL transcript into a list of parsed objects (Claude format)."""
    results = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError) as e:
        from rainman.core.log import get_logger
        get_logger("hooks.session_end").warning("could not read transcript: %s", e)
    return results


def _extract_assistant_text(transcript_lines):
    """Extract assistant message text from Claude Code transcript entries."""
    texts = []
    for entry in transcript_lines:
        role = entry.get("role", "")
        if role == "assistant":
            content = entry.get("content", "")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text", "")
                        if text:
                            texts.append(text)
                    elif isinstance(block, str):
                        texts.append(block)
        message = entry.get("message", {})
        if isinstance(message, dict) and message.get("role") == "assistant":
            content = message.get("content", "")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text", "")
                        if text:
                            texts.append(text)
    return "\n".join(texts)


if __name__ == "__main__":
    main()
