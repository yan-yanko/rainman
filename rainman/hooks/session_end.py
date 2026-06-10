#!/usr/bin/env python3
"""
SessionEnd Hook — Capture Key Decisions
=========================================

Fires when Claude Code ends a session.
Reads the conversation transcript (JSONL), extracts key decisions,
patterns, and failures using keyword matching (zero LLM), and
stores them as Rainman memories.

Register in .claude/settings.json:
{
    "hooks": {
        "SessionEnd": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": "python -m rainman.hooks.session_end"
            }]
        }]
    }
}
"""

import json
import os
import re
import sys


# Maximum memories to create per session
MAX_MEMORIES_PER_SESSION = 5

# Minimum transcript lines to bother processing
MIN_TRANSCRIPT_LINES = 10

# Snippet radius around keyword match (chars before + after)
SNIPPET_RADIUS = 100

# Keyword groups → category mapping
KEYWORD_GROUPS = {
    "decision": [
        "decided to",
        "the approach is",
        "going with",
        "chose to",
        "solution is",
        "the fix is",
        "we'll use",
        "the plan is",
        "architecture:",
        "design:",
        "the enterprise play",
        "the pitch is",
        "the product is",
        "the moat is",
        "differentiator",
        "the strategy is",
        "positioning:",
    ],
    "pattern": [
        "pattern:",
        "convention:",
        "always use",
        "never use",
        "rule:",
        "best practice",
        "the way to",
        "the market is",
        "competitors",
        "the gap is",
        "nobody is building",
        "unmet need",
        "proven demand",
    ],
    "failure": [
        "root cause",
        "failed because",
        "the issue was",
        "bug was",
        "broke because",
        "the problem was",
        "regression",
        "no moat",
        "no real use case",
        "overclaim",
        "doesn't actually",
    ],
    "note": [
        "important:",
        "critical:",
        "remember that",
        "remember this:",
        "remember this",
        "store this",
        "don't forget",
        "key insight",
        "note:",
        "learned that",
        "turns out",
        "validated:",
        "research shows",
        "the honest answer",
        "the data says",
        "market size",
        "pricing:",
    ],
}

# Dedup threshold — skip if recall top score exceeds this
DEDUP_SCORE_THRESHOLD = 0.8


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception) as e:
        print(f"[rainman] session_end: failed to parse input: {e}", file=sys.stderr)
        sys.exit(0)

    # Skip if user explicitly cleared the session
    reason = hook_input.get("reason", "")
    if reason == "clear":
        sys.exit(0)

    cwd = hook_input.get("cwd", os.getcwd())
    transcript_path = hook_input.get("transcript_path", "")

    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    # Read transcript
    lines = _read_transcript(transcript_path)
    if len(lines) < MIN_TRANSCRIPT_LINES:
        sys.exit(0)

    # Extract assistant text from transcript
    assistant_text = _extract_assistant_text(lines)
    if not assistant_text:
        sys.exit(0)

    # Find key snippets
    snippets = _extract_key_snippets(assistant_text)
    if not snippets:
        sys.exit(0)

    from rainman.core.engine import RainmanEngine
    from rainman.core.redact import redact_content

    engine = RainmanEngine(project_dir=cwd)

    stored = 0
    for content, category in snippets:
        if stored >= MAX_MEMORIES_PER_SESSION:
            break

        # Redact secrets before storing
        content = redact_content(content)
        if len(content.replace("[REDACTED]", "").strip()) < 30:
            continue

        # Dedup: refresh existing memory instead of creating duplicate
        existing = engine.recall(content, limit=1)
        if existing and existing[0].total_score > DEDUP_SCORE_THRESHOLD:
            engine.refresh(existing[0].memory.id)
            continue

        engine.add(
            content=content,
            category=category,
            source="hook:session_end",
            layer="project",
        )
        stored += 1

    # Silent — no stdout (session is ending, no context to inject)
    sys.exit(0)


def _read_transcript(path):
    """Read JSONL transcript file, return list of parsed objects."""
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
        print(f"[rainman] session_end: could not read transcript: {e}", file=sys.stderr)
    return results


def _extract_assistant_text(transcript_lines):
    """Extract all assistant message text from transcript entries."""
    texts = []
    for entry in transcript_lines:
        # Claude Code transcripts have varying formats — try common structures
        role = entry.get("role", "")
        if role == "assistant":
            # Text may be in "content" (string or list of blocks)
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
        # Also check for "message" wrapper
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


def _extract_key_snippets(text):
    """Scan text for keyword matches, extract snippets with category."""
    text_lower = text.lower()
    found = []  # (content, category, position)

    for category, keywords in KEYWORD_GROUPS.items():
        for keyword in keywords:
            # Find all occurrences
            start = 0
            while True:
                idx = text_lower.find(keyword, start)
                if idx == -1:
                    break

                # Extract snippet around the match
                snippet_start = max(0, idx - SNIPPET_RADIUS)
                snippet_end = min(len(text), idx + len(keyword) + SNIPPET_RADIUS)

                # Extend to word boundaries
                if snippet_start > 0:
                    space_idx = text.rfind(" ", snippet_start - 20, snippet_start)
                    if space_idx != -1:
                        snippet_start = space_idx + 1

                if snippet_end < len(text):
                    space_idx = text.find(" ", snippet_end, snippet_end + 20)
                    if space_idx != -1:
                        snippet_end = space_idx

                snippet = text[snippet_start:snippet_end].strip()

                # Clean up: remove partial sentences at boundaries
                snippet = _clean_snippet(snippet)

                if len(snippet) >= 30:  # Skip tiny fragments
                    found.append((snippet, category, idx))

                start = idx + len(keyword)

    # Sort by position in text (later = more likely to be final decisions)
    found.sort(key=lambda x: x[2], reverse=True)

    # Deduplicate overlapping snippets
    seen_positions = []
    unique = []
    for content, category, pos in found:
        # Skip if too close to an already-selected snippet
        if any(abs(pos - sp) < SNIPPET_RADIUS for sp in seen_positions):
            continue
        seen_positions.append(pos)
        unique.append((content, category))

    return unique[:MAX_MEMORIES_PER_SESSION * 2]  # Return extra for dedup filtering


def _clean_snippet(text):
    """Clean a snippet for storage: normalize whitespace, trim noise."""
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove common noise from transcript format
    text = text.strip("- *`")
    return text.strip()


if __name__ == "__main__":
    main()
