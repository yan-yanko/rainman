"""
Git History Ingest
===================

Parse git log into memories. Each commit becomes a memory
with category inferred from commit message patterns.

Usage:
    rainman ingest --git
    rainman ingest --git --limit 50
"""

import os
import re
import subprocess
from typing import List, Tuple


# Patterns to infer category from commit messages
_CATEGORY_PATTERNS = [
    (r"\bfix(?:ed|es|ing)?\b", "solution"),
    (r"\bbug\b", "failure"),
    (r"\bbreak(?:ing|s)?\b", "failure"),
    (r"\brevert\b", "failure"),
    (r"\brefactor\b", "pattern"),
    (r"\bpattern\b", "pattern"),
    (r"\bconvention\b", "convention"),
    (r"\bstyle\b", "convention"),
    (r"\blint\b", "convention"),
    (r"\bdecid(?:e|ed|es|ing)\b", "decision"),
    (r"\bchoose\b", "decision"),
    (r"\bmigrat(?:e|ed|ion)\b", "decision"),
    (r"\bfeat(?:ure)?\b", "note"),
    (r"\badd(?:ed|s|ing)?\b", "note"),
]


def _infer_category(message: str) -> str:
    """Infer memory category from commit message."""
    lower = message.lower()
    for pattern, category in _CATEGORY_PATTERNS:
        if re.search(pattern, lower):
            return category
    return "note"


def _parse_files_changed(diff_stat: str) -> List[str]:
    """Extract file paths from git diff --stat output."""
    files = []
    for line in diff_stat.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("(") or "|" not in line:
            continue
        file_part = line.split("|")[0].strip()
        if file_part:
            files.append(file_part)
    return files


def parse_git_log(project_dir: str, limit: int = 50) -> List[Tuple[str, str, str, List[str]]]:
    """
    Parse git log into (content, category, source, file_refs) tuples.

    Returns list of tuples ready for engine.add().
    """
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--max-count={limit}",
                "--format=%H|%s|%an|%ad",
                "--date=short",
                "--name-only",
            ],
            capture_output=True,
            text=True,
            cwd=project_dir,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    entries = []
    lines = result.stdout.strip().split("\n")

    current_hash = None
    current_msg = None
    current_author = None
    current_date = None
    current_files = []

    for line in lines:
        line = line.strip()
        if not line:
            # Blank line separates commits from file lists
            if current_hash and current_files:
                # Flush previous commit
                _flush_commit(
                    entries, current_hash, current_msg,
                    current_author, current_date, current_files,
                )
                current_files = []
            continue

        if "|" in line and line.count("|") >= 3:
            # This is a commit header line
            if current_hash:
                _flush_commit(
                    entries, current_hash, current_msg,
                    current_author, current_date, current_files,
                )
                current_files = []

            parts = line.split("|", 3)
            current_hash = parts[0][:8]
            current_msg = parts[1]
            current_author = parts[2]
            current_date = parts[3]
        else:
            # File path from --name-only
            current_files.append(line)

    # Flush last commit
    if current_hash:
        _flush_commit(
            entries, current_hash, current_msg,
            current_author, current_date, current_files,
        )

    return entries


def _flush_commit(entries, hash_short, msg, author, date, files):
    """Build a memory entry from a parsed commit."""
    category = _infer_category(msg)
    file_refs = [f for f in files if f and not f.startswith("(")][:5]  # cap at 5

    content = f"[{date}] {msg}"
    if file_refs:
        content += f" (files: {', '.join(file_refs[:3])})"

    source = f"git:{hash_short}"

    entries.append((content, category, source, file_refs))


def ingest_git(project_dir: str, limit: int = 50) -> int:
    """
    Ingest git history into Rainman memory.

    Returns number of memories added.
    """
    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=project_dir)
    entries = parse_git_log(project_dir, limit=limit)

    count = 0
    for content, category, source, file_refs in entries:
        engine.add(
            content=content,
            category=category,
            file_refs=file_refs,
            source=source,
            layer="project",
        )
        count += 1

    return count
