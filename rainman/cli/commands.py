"""
Rainman CLI Commands
=====================

All commands operate on layered storage (global + project).
"""

import json
import os
import sys
from typing import List, Optional

from rainman.core.engine import RainmanEngine
from rainman.core.store import MemoryStore


def _get_engine(project_dir: Optional[str] = None) -> RainmanEngine:
    """Create engine, auto-detecting project dir if not specified."""
    if project_dir is None:
        # Walk up from cwd looking for .rainman/
        cwd = os.getcwd()
        check = cwd
        while True:
            if os.path.isdir(os.path.join(check, ".rainman")):
                project_dir = check
                break
            parent = os.path.dirname(check)
            if parent == check:
                break
            check = parent
        if project_dir is None:
            project_dir = cwd

    return RainmanEngine(project_dir=project_dir)


def cmd_init(project_dir: Optional[str] = None) -> None:
    """Initialize .rainman/ in project directory."""
    target = project_dir or os.getcwd()
    store = MemoryStore(project_dir=target)
    path = store.init_project(target)
    store.init_global()
    print(f"Initialized Rainman at {path}")
    print(f"Global store at {os.path.expanduser('~/.rainman/')}")


def cmd_add(
    content: str,
    category: str = "note",
    tags: Optional[List[str]] = None,
    file_refs: Optional[List[str]] = None,
    is_global: bool = False,
) -> None:
    """Add a memory."""
    engine = _get_engine()
    layer = "global" if is_global else "project"
    m = engine.add(
        content=content,
        category=category,
        tags=tags or [],
        file_refs=file_refs or [],
        source="cli",
        layer=layer,
    )
    print(f"Added [{m.category}] {m.content[:80]}")
    print(f"  id: {m.id}")
    print(f"  sentiment: {m.sentiment}")
    print(f"  importance: {m.importance:.2f}")
    print(f"  layer: {m.layer}")
    if m.linked_ids:
        print(f"  linked to: {len(m.linked_ids)} memories")


def cmd_recall(
    query: str,
    limit: int = 5,
    category: Optional[str] = None,
) -> None:
    """Search memories by query."""
    engine = _get_engine()
    results = engine.recall(query, limit=limit, category=category)

    if not results:
        print("No memories found.")
        return

    for i, r in enumerate(results, 1):
        m = r.memory
        print(f"\n{i}. [{m.category}] {m.content[:120]}")
        print(f"   score: {r.total_score:.3f} "
              f"(kw:{r.keyword_score:.2f} rec:{r.recency_score:.2f} "
              f"imp:{r.importance_score:.2f} assoc:{r.associative_score:.2f})")
        if m.tags:
            print(f"   tags: {', '.join(m.tags)}")
        if m.file_refs:
            print(f"   files: {', '.join(m.file_refs)}")
        print(f"   [{m.layer}] recalled {m.recall_count}x | {m.sentiment}")


def cmd_status() -> None:
    """Show memory statistics."""
    engine = _get_engine()
    stats = engine.get_stats()

    print(f"Rainman Memory Status")
    print(f"{'=' * 40}")
    print(f"Total memories: {stats['total']}")
    print()

    if stats["by_layer"]:
        print("By layer:")
        for layer, count in stats["by_layer"].items():
            print(f"  {layer}: {count}")

    if stats["by_category"]:
        print("\nBy category:")
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {cat}: {count}")

    if stats["by_sentiment"]:
        print("\nBy sentiment:")
        for sent, count in sorted(stats["by_sentiment"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {sent}: {count}")

    if stats["top_tags"]:
        print("\nTop tags:")
        for tag, count in stats["top_tags"]:
            print(f"  {tag}: {count}")


def cmd_links(ref: str) -> None:
    """Show memories linked to a file or concept."""
    engine = _get_engine()
    results = engine.links(ref)

    if not results:
        print(f"No memories linked to '{ref}'")
        return

    print(f"Memories linked to '{ref}':")
    for i, m in enumerate(results, 1):
        print(f"\n{i}. [{m.category}] {m.content[:120]}")
        if m.file_refs:
            print(f"   files: {', '.join(m.file_refs)}")
        if m.tags:
            print(f"   tags: {', '.join(m.tags)}")


def cmd_export() -> None:
    """Export all memories as JSON to stdout."""
    engine = _get_engine()
    memories = engine.get_all()
    json.dump([m.to_dict() for m in memories], sys.stdout, indent=2)
    print()  # trailing newline


def cmd_context(limit: int = 10) -> None:
    """Show current working context (recent + important)."""
    engine = _get_engine()
    results = engine.context(limit=limit)

    if not results:
        print("No memories yet.")
        return

    print("Current context:")
    for i, r in enumerate(results, 1):
        m = r.memory
        print(f"  {i}. [{m.category}] {m.content[:100]}")


def cmd_ingest(git: bool = False, files: bool = False, limit: int = 50, depth: int = 4) -> None:
    """Ingest project history and structure into memory."""
    if not git and not files:
        print("Specify --git and/or --files")
        return

    project_dir = os.getcwd()
    # Walk up to find .rainman/
    check = project_dir
    while True:
        if os.path.isdir(os.path.join(check, ".rainman")):
            project_dir = check
            break
        parent = os.path.dirname(check)
        if parent == check:
            break
        check = parent

    total = 0

    if git:
        from rainman.ingest.git import ingest_git
        count = ingest_git(project_dir, limit=limit)
        print(f"Ingested {count} memories from git history")
        total += count

    if files:
        from rainman.ingest.files import ingest_files
        count = ingest_files(project_dir, max_depth=depth)
        print(f"Ingested {count} memories from file structure")
        total += count

    print(f"\nTotal: {total} memories added")
