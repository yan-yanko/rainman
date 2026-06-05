"""
File Structure Ingest
======================

Scan project file tree and create memories about what exists.
Extracts module-level docstrings and first comment blocks.

Usage:
    rainman ingest --files
    rainman ingest --files --depth 3
"""

import os
import re
from typing import List, Tuple


# File extensions we care about
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".rs", ".go", ".java", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp",
    ".sh", ".bash", ".zsh",
    ".sql", ".graphql",
    ".yaml", ".yml", ".toml", ".json",
    ".md", ".rst", ".txt",
}

# Directories to always skip
_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".venv", "venv",
    ".env", "dist", "build", ".next", ".nuxt",
    ".rainman", ".claude", "egg-info",
}

# Max files to ingest (safety cap)
MAX_FILES = 200


def _extract_summary(file_path: str) -> str:
    """Extract a brief summary from a source file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(2000)  # First 2KB only
    except (OSError, IOError):
        return ""

    ext = os.path.splitext(file_path)[1].lower()

    # Python: extract module docstring
    if ext == ".py":
        match = re.search(r'^"""(.*?)"""', content, re.DOTALL)
        if not match:
            match = re.search(r"^'''(.*?)'''", content, re.DOTALL)
        if match:
            doc = match.group(1).strip()
            # Take first meaningful line
            for line in doc.split("\n"):
                line = line.strip()
                if line and not line.startswith("=") and not line.startswith("-"):
                    return line[:150]

    # JS/TS: extract first JSDoc or block comment
    if ext in (".js", ".ts", ".tsx", ".jsx"):
        match = re.search(r"/\*\*(.*?)\*/", content, re.DOTALL)
        if match:
            doc = match.group(1).strip()
            for line in doc.split("\n"):
                line = line.strip().lstrip("* ").strip()
                if line and not line.startswith("@"):
                    return line[:150]

    # For any file: first non-empty, non-comment line
    for line in content.split("\n")[:20]:
        line = line.strip()
        if (line and not line.startswith("#") and not line.startswith("//")
                and not line.startswith("/*") and not line.startswith("*")
                and not line.startswith("import ") and not line.startswith("from ")
                and not line.startswith("use ") and not line.startswith("package ")
                and len(line) > 10):
            return line[:150]

    return ""


def scan_project(project_dir: str, max_depth: int = 4) -> List[Tuple[str, str]]:
    """
    Scan project tree and return (relative_path, summary) tuples.

    Only includes code files with extractable summaries.
    """
    results = []
    base = os.path.normpath(project_dir)

    for root, dirs, files in os.walk(base):
        # Filter out skip dirs (in-place to prevent os.walk from descending)
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]

        # Check depth
        rel_root = os.path.relpath(root, base)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        if depth > max_depth:
            dirs.clear()
            continue

        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _CODE_EXTENSIONS:
                continue

            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, base).replace("\\", "/")

            summary = _extract_summary(full_path)
            if summary:
                results.append((rel_path, summary))

            if len(results) >= MAX_FILES:
                return results

    return results


def ingest_files(project_dir: str, max_depth: int = 4) -> int:
    """
    Ingest project file structure into Rainman memory.

    Returns number of memories added.
    """
    from rainman.core.engine import RainmanEngine

    engine = RainmanEngine(project_dir=project_dir)
    scanned = scan_project(project_dir, max_depth=max_depth)

    count = 0
    for rel_path, summary in scanned:
        content = f"File {rel_path}: {summary}"
        engine.add(
            content=content,
            category="note",
            file_refs=[rel_path],
            source="ingest:files",
            layer="project",
        )
        count += 1

    return count
