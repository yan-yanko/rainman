#!/usr/bin/env python3
"""
PostCompact Hook — The Killer Feature
=======================================

Fires when Claude Code compacts context (long sessions).
This is EXACTLY when memories get lost.

Reads compaction event, extracts current working topic,
recalls relevant memories, and outputs them to stdout
for re-injection into Claude's context.

Register in .claude/settings.json:
{
    "hooks": {
        "PostCompact": [{
            "matcher": "auto",
            "hooks": [{
                "type": "command",
                "command": "python -m rainman.hooks.post_compact"
            }]
        }]
    }
}
"""

import json
import os
import sys


def main():
    # Read compaction event from stdin
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception):
        hook_input = {}

    cwd = hook_input.get("cwd", os.getcwd())

    # Try to extract working topic from the compaction summary
    summary = hook_input.get("summary", "")
    transcript = hook_input.get("transcript_snippet", "")

    # Build a search query from available context
    query_parts = []
    if summary:
        # Take key words from summary
        query_parts.append(summary[:200])
    if transcript:
        query_parts.append(transcript[:200])

    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=cwd)

    lines = ["[Rainman] Re-injecting project memory after context compaction:\n"]

    if query_parts:
        # Recall by topic
        query = " ".join(query_parts)
        results = engine.recall(query, limit=5)
        if results:
            lines.append("Relevant to current work:")
            for i, r in enumerate(results, 1):
                m = r.memory
                line = f"  {i}. [{m.category}] {m.content[:150]}"
                if m.file_refs:
                    line += f"\n     files: {', '.join(m.file_refs)}"
                lines.append(line)
            lines.append("")

    # Always include high-importance context regardless of topic
    context = engine.context(limit=5)
    if context:
        lines.append("High-importance project knowledge:")
        for i, r in enumerate(context, 1):
            m = r.memory
            # Skip if already included above
            line = f"  {i}. [{m.category}] {m.content[:150]}"
            if m.file_refs:
                line += f"\n     files: {', '.join(m.file_refs)}"
            lines.append(line)

    lines.append(
        "\nUse `recall` to search for specific knowledge. "
        "Use `remember` to save important learnings before next compaction."
    )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
