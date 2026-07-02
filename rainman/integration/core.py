"""Host-agnostic integration behaviours.

These are the automatic behaviours that make Rainman surface memory without
being asked — expressed independent of any AI coding host. Each takes a plain
``RainmanEngine`` plus normalised arguments (never a host's raw event). A host
adapter (Claude Code hook, git hook, ...) is responsible for translating its
native event into these calls and for delivering any returned text.

Behaviours
----------
- ``auto_pull(engine)``                          best-effort sync from a remote
- ``session_start_context(engine)``              text to inject at session start
- ``compaction_context(engine, topic_query)``    text to re-inject after compaction
- ``learn_from_tool(engine, name, in_, out, cwd)`` learn from a tool action
- ``capture_learnings(engine, text, cwd)``        mine a transcript for decisions

Zero LLM calls; zero host coupling.
"""

import os
import re
from typing import Optional

# --- constants (moved verbatim from the hooks) -------------------------------
WATCHED_TOOLS = {"Read", "Edit", "Write", "Bash"}
MIN_CONTENT_LENGTH = 50
BASH_OUTCOME_KEYWORDS = ("pytest", "test", "build", "deploy", "migrate")

MAX_MEMORIES_PER_SESSION = 5
SNIPPET_RADIUS = 100
DEDUP_SCORE_THRESHOLD = 0.8

# Keyword groups → category mapping (transcript mining).
KEYWORD_GROUPS = {
    "decision": [
        "decided to", "the approach is", "going with", "chose to", "solution is",
        "the fix is", "we'll use", "the plan is", "architecture:", "design:",
        "the enterprise play", "the pitch is", "the product is", "the moat is",
        "differentiator", "the strategy is", "positioning:",
    ],
    "pattern": [
        "pattern:", "convention:", "always use", "never use", "rule:",
        "best practice", "the way to", "the market is", "competitors",
        "the gap is", "nobody is building", "unmet need", "proven demand",
    ],
    "failure": [
        "root cause", "failed because", "the issue was", "bug was",
        "broke because", "the problem was", "regression", "no moat",
        "no real use case", "overclaim", "doesn't actually",
    ],
    "note": [
        "important:", "critical:", "remember that", "remember this:",
        "remember this", "store this", "don't forget", "key insight", "note:",
        "learned that", "turns out", "validated:", "research shows",
        "the honest answer", "the data says", "market size", "pricing:",
    ],
}


# --- sync --------------------------------------------------------------------
def auto_pull(engine) -> None:
    """Pull from the sync remote if one is configured. Never raises."""
    try:
        from rainman.sync import SyncClient, SyncError
        client = SyncClient(engine)
        if client.is_configured():
            client.pull()
    except (SyncError, Exception) as e:  # noqa: BLE001 - must never block a host
        from rainman.core.log import get_logger
        get_logger("integration.core").warning("auto-pull skipped: %s", e)


# --- context injection -------------------------------------------------------
# Unsolicited context injection is the dangerous poisoning path (no query, no
# user choice), so third-party (ingest/git) memories are held out of it by
# default. Explicit `recall` still surfaces them. The floor is org-policy
# configurable via ``auto_inject_min_trust``.

def session_start_context(engine) -> Optional[str]:
    """General project context for a fresh/resumed session, or None if empty."""
    floor = engine.policy.get("auto_inject_min_trust")
    results = engine.context(limit=8, min_trust=floor)
    if not results:
        return None

    lines = ["[Rainman] Project memory loaded:\n"]
    for i, r in enumerate(results, 1):
        m = r.memory
        line = f"  {i}. [{m.category}] {m.content[:120]}"
        if m.file_refs:
            line += f" (files: {', '.join(m.file_refs)})"
        line += f"\n     trust: {m.trust} | source: {m.source or 'unknown'}"
        lines.append(line)
    lines.append(
        "\nUse the `recall` tool to search for more specific knowledge. "
        "Use `remember` to save new learnings."
    )
    return "\n".join(lines)


def compaction_context(engine, topic_query: str = "") -> str:
    """Topical + high-importance memory to re-inject after context compaction."""
    lines = ["[Rainman] Re-injecting project memory after context compaction:\n"]
    seen_ids = set()
    floor = engine.policy.get("auto_inject_min_trust")

    if topic_query:
        # Still unsolicited (compaction-triggered), so the auto-inject floor applies.
        results = engine.recall(topic_query, limit=5, min_trust=floor)
        if results:
            lines.append("Relevant to current work:")
            for i, r in enumerate(results, 1):
                m = r.memory
                seen_ids.add(m.id)
                line = f"  {i}. [{m.category}] {m.content[:150]}"
                if m.file_refs:
                    line += f"\n     files: {', '.join(m.file_refs)}"
                line += f"\n     trust: {m.trust} | source: {m.source or 'unknown'}"
                lines.append(line)
            lines.append("")

    context = engine.context(limit=5, min_trust=floor)
    important = [r for r in context if r.memory.id not in seen_ids]
    if important:
        lines.append("High-importance project knowledge:")
        for i, r in enumerate(important, 1):
            m = r.memory
            line = f"  {i}. [{m.category}] {m.content[:150]}"
            if m.file_refs:
                line += f"\n     files: {', '.join(m.file_refs)}"
            line += f"\n     trust: {m.trust} | source: {m.source or 'unknown'}"
            lines.append(line)

    lines.append(
        "\nUse `recall` to search for specific knowledge. "
        "Use `remember` to save important learnings before next compaction."
    )
    return "\n".join(lines)


# --- learn from a tool action (Read/Edit/Write/Bash) -------------------------
def _coerce_output(resp) -> str:
    """Normalise a tool result into searchable text (str, or a dict like Bash's
    {stdout, stderr, ...}, or a list)."""
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


def _short_path(path):
    parts = path.replace("\\", "/").split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return path


def _project_relative(path, root):
    """Store file refs relative to the project root so memories stay portable
    across machines (and don't leak absolute local paths when committed).
    Paths outside the tree are left as-is rather than emitting a ``..`` ladder."""
    if not path or not root:
        return path
    try:
        rel = os.path.relpath(path, root)
    except (ValueError, OSError):
        return path  # e.g. different drive on Windows
    if rel.startswith("..") or os.path.isabs(rel):
        return path
    return rel.replace("\\", "/")


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


def _extract_learning(tool_name, tool_input, tool_output):
    """Extract (content, category, file_refs) from a Read/Edit action, or None."""
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return None
        output_str = str(tool_output)[:500] if tool_output else ""
        if len(output_str) < MIN_CONTENT_LENGTH:
            return None
        lines = [ln.strip() for ln in output_str.split("\n")
                 if ln.strip() and not ln.strip().startswith("#")]
        summary = lines[0][:150] if lines else "file contents"
        return (f"File {_short_path(file_path)}: {summary}", "note", [file_path])

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
    # Bash is handled separately (typed-causal experience cards).
    return None


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
        safe = safe_content(problem, extra_patterns=engine.policy.get("extra_redaction_patterns"))
        if safe is None:
            return
        engine.record_failure(
            problem=safe, command=command, file_refs=file_refs,
            source="hook:post_tool_use:Bash",
        )
        return

    if passed:
        open_failure = engine.find_open_failure(file_refs)
        if open_failure is not None:
            engine.resolve_failure(
                open_failure, fix=f"{command[:120]} now passes",
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


def learn_from_tool(engine, tool_name, tool_input, tool_output, cwd) -> None:
    """Auto-learn from a single tool action (Read/Edit/Write/Bash). Silent,
    salience-gated, secret-redacted, dedup-refreshing. No-op for other tools or
    when org policy disables auto-learn."""
    if tool_name not in WATCHED_TOOLS:
        return
    if engine.policy.get("disable_auto_learn"):
        return

    if tool_name == "Bash":
        _handle_bash(engine, tool_input.get("command", ""), tool_output, cwd)
        return

    from rainman.core.redact import safe_content
    from rainman.core.salience import is_salient, salience_score

    learning = _extract_learning(tool_name, tool_input, tool_output)
    if not learning:
        return
    content, category, file_refs = learning
    file_refs = [_project_relative(f, cwd) for f in file_refs]

    if len(content) < MIN_CONTENT_LENGTH:
        return

    score = salience_score(category, content, file_refs)
    if not is_salient(category, content, file_refs):
        return

    safe = safe_content(
        content,
        file_path=file_refs[0] if file_refs else None,
        extra_patterns=engine.policy.get("extra_redaction_patterns"),
        extra_path_denylist=engine.policy.get("path_denylist"),
    )
    if safe is None:
        return
    content = safe

    if file_refs:
        existing = engine.links(file_refs[0])
        for m in existing:
            if m.source and m.source.startswith(f"hook:post_tool_use:{tool_name}"):
                engine.refresh(m.id)
                return

    engine.add(
        content=content, category=category, file_refs=file_refs,
        source=f"hook:post_tool_use:{tool_name}", layer="project",
        metadata={"salience": round(score, 2)},
    )


# --- capture learnings from a transcript's assistant text --------------------
def _clean_snippet(text):
    text = re.sub(r"\s+", " ", text)
    text = text.strip("- *`")
    return text.strip()


def _extract_key_snippets(text):
    """Scan assistant text for keyword matches, extract (content, category)."""
    text_lower = text.lower()
    found = []  # (content, category, position)
    for category, keywords in KEYWORD_GROUPS.items():
        for keyword in keywords:
            start = 0
            while True:
                idx = text_lower.find(keyword, start)
                if idx == -1:
                    break
                snippet_start = max(0, idx - SNIPPET_RADIUS)
                snippet_end = min(len(text), idx + len(keyword) + SNIPPET_RADIUS)
                if snippet_start > 0:
                    space_idx = text.rfind(" ", snippet_start - 20, snippet_start)
                    if space_idx != -1:
                        snippet_start = space_idx + 1
                if snippet_end < len(text):
                    space_idx = text.find(" ", snippet_end, snippet_end + 20)
                    if space_idx != -1:
                        snippet_end = space_idx
                snippet = _clean_snippet(text[snippet_start:snippet_end].strip())
                if len(snippet) >= 30:
                    found.append((snippet, category, idx))
                start = idx + len(keyword)

    found.sort(key=lambda x: x[2], reverse=True)
    seen_positions, unique = [], []
    for content, category, pos in found:
        if any(abs(pos - sp) < SNIPPET_RADIUS for sp in seen_positions):
            continue
        seen_positions.append(pos)
        unique.append((content, category))
    return unique[:MAX_MEMORIES_PER_SESSION * 2]


def capture_learnings(engine, assistant_text: str, cwd=None,
                      source: str = "hook:session_end") -> int:
    """Mine assistant text for key decisions/patterns/failures and store them
    (salience via keyword groups, secret-redacted, dedup-refreshing). Returns
    the number stored. No-op when org policy disables auto-learn."""
    if engine.policy.get("disable_auto_learn"):
        return 0
    if not assistant_text:
        return 0
    snippets = _extract_key_snippets(assistant_text)
    if not snippets:
        return 0

    from rainman.core.redact import redact_content
    extra_patterns = engine.policy.get("extra_redaction_patterns")

    stored = 0
    for content, category in snippets:
        if stored >= MAX_MEMORIES_PER_SESSION:
            break
        content = redact_content(content, extra_patterns=extra_patterns)
        if len(content.replace("[REDACTED]", "").strip()) < 30:
            continue
        existing = engine.recall(content, limit=1)
        if existing and existing[0].total_score > DEDUP_SCORE_THRESHOLD:
            engine.refresh(existing[0].memory.id)
            continue
        engine.add(content=content, category=category, source=source, layer="project")
        stored += 1
    return stored


def maybe_sleep(engine) -> dict:
    """Optionally run the consolidation/forgetting 'sleep' pass at session end —
    the human analog of offline memory reorganization. Off by default; enable
    with org/project policy ``consolidate_on_session_end``. Never raises."""
    if not engine.policy.get("consolidate_on_session_end"):
        return {"n_promoted": 0, "n_forgotten": 0, "promoted": [], "forgotten": []}
    try:
        return engine.consolidate()
    except Exception as e:  # noqa: BLE001 - must never block session end
        from rainman.core.log import get_logger
        get_logger("integration.core").warning("sleep pass skipped: %s", e)
        return {"n_promoted": 0, "n_forgotten": 0, "promoted": [], "forgotten": []}


# --- learn from a git commit (host-independent — works in ANY editor) --------
# Trivial commits that carry no reusable knowledge.
_TRIVIAL_COMMIT_PREFIXES = (
    "wip", "merge ", "merge branch", "merge pull", "bump", "typo", "fixup!",
    "squash!", "revert \"merge", "chore(release)", "release ",
)


def _commit_category(message_lower: str) -> str:
    if any(k in message_lower for k in ("revert", "broke", "regress", "hotfix")):
        return "failure"
    if any(k in message_lower for k in ("fix", "resolve", "patch", "bugfix")):
        return "solution"
    if any(k in message_lower for k in ("refactor", "redesign", "switch to",
                                        "migrate", "decision", "adopt")):
        return "decision"
    return "note"


def learn_from_commit(engine, message: str, changed_files, cwd=None,
                      source: str = "hook:git:post-commit"):
    """Store one git commit as project memory — the host-independent auto-learn
    path (a post-commit hook runs this regardless of which editor made the
    commit). Salience-gated, secret-redacted, dedup-refreshing. Returns the
    stored Memory or None. No-op on trivial commits or when auto-learn is off."""
    if engine.policy.get("disable_auto_learn"):
        return None
    msg = (message or "").strip()
    if len(msg) < 15:
        return None
    low = msg.lower()
    if any(low.startswith(p) for p in _TRIVIAL_COMMIT_PREFIXES):
        return None

    from rainman.core.redact import safe_content
    from rainman.core.salience import is_salient, salience_score

    category = _commit_category(low)
    content = f"Commit: {msg[:300]}"
    file_refs = [_project_relative(f, cwd) for f in (changed_files or []) if f]

    if not is_salient(category, content, file_refs):
        return None

    safe = safe_content(
        content,
        extra_patterns=engine.policy.get("extra_redaction_patterns"),
        extra_path_denylist=engine.policy.get("path_denylist"),
    )
    if safe is None:
        return None
    content = safe

    existing = engine.recall(content, limit=1)
    if existing and existing[0].total_score > DEDUP_SCORE_THRESHOLD:
        engine.refresh(existing[0].memory.id)
        return None

    return engine.add(
        content=content, category=category, file_refs=file_refs,
        source=source, layer="project",
        metadata={"salience": round(salience_score(category, content, file_refs), 2)},
    )
