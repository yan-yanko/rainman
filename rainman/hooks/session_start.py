#!/usr/bin/env python3
"""
SessionStart Hook
==================

Fires when Claude Code starts or resumes a session, or after compaction.
Outputs project context (recent + important memories) to stdout.
Claude sees this as fresh context.

Sources:
  - startup: New session → load general project context
  - resume:  Resumed session → load general project context
  - compact: After context compaction → re-inject topical + important memories
             (This is the killer feature — recovers knowledge lost to compaction)

Register in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [
            {
                "matcher": "",
                "hooks": [{
                    "type": "command",
                    "command": "python -m rainman.hooks.session_start"
                }]
            }
        ]
    }
}

An empty matcher fires on all sources (startup, resume, compact).
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
    source = hook_input.get("source", "startup")

    # Import here to keep startup fast
    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=cwd)

    if source == "compact":
        _handle_compaction(engine, hook_input)
    else:
        _handle_session_start(engine)


def _handle_session_start(engine):
    """Normal session start — load general project context."""
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


def _handle_compaction(engine, hook_input):
    """Post-compaction — re-inject topical + important memories."""
    # Try to build a topical query from transcript
    transcript_path = hook_input.get("transcript_path", "")
    query = _extract_recent_topic(transcript_path)

    lines = ["[Rainman] Re-injecting project memory after context compaction:\n"]

    seen_ids = set()

    if query:
        # Recall by topic — surface memories relevant to current work
        results = engine.recall(query, limit=5)
        if results:
            lines.append("Relevant to current work:")
            for i, r in enumerate(results, 1):
                m = r.memory
                seen_ids.add(m.id)
                line = f"  {i}. [{m.category}] {m.content[:150]}"
                if m.file_refs:
                    line += f"\n     files: {', '.join(m.file_refs)}"
                lines.append(line)
            lines.append("")

    # Always include high-importance context regardless of topic
    context = engine.context(limit=5)
    important = [r for r in context if r.memory.id not in seen_ids]
    if important:
        lines.append("High-importance project knowledge:")
        for i, r in enumerate(important, 1):
            m = r.memory
            line = f"  {i}. [{m.category}] {m.content[:150]}"
            if m.file_refs:
                line += f"\n     files: {', '.join(m.file_refs)}"
            lines.append(line)

    lines.append(
        "\nUse `recall` to search for specific knowledge. "
        "Use `remember` to save important learnings before next compaction."
    )

    print("\n".join(lines))


def _extract_recent_topic(transcript_path):
    """
    Extract recent topic from conversation transcript for topical recall.
    Returns a query string or empty string if unavailable.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return ""

    try:
        # Read last N lines of transcript to get recent topic
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Take last 20 entries
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

            # Extract assistant text (reuse session_end's logic)
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

            # Also check "message" wrapper
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
            # Combine recent text into a search query (last 500 chars)
            combined = " ".join(texts)
            return combined[-500:]

    except (OSError, IOError):
        pass

    return ""


if __name__ == "__main__":
    main()
