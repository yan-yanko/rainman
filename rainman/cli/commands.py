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


def cmd_setup() -> None:
    """One-command setup: init project + register MCP server + configure hooks."""
    import shutil
    import subprocess

    project_dir = os.getcwd()
    errors = []

    # Step 1: Init .rainman/
    print("1. Initializing .rainman/ ...")
    store = MemoryStore(project_dir=project_dir)
    path = store.init_project(project_dir)
    store.init_global()
    print(f"   Done: {path}")

    # Step 2: Register MCP server with Claude Code
    print("\n2. Registering MCP server with Claude Code ...")
    python_path = sys.executable
    claude_path = shutil.which("claude")
    if claude_path:
        try:
            result = subprocess.run(
                [claude_path, "mcp", "add", "rainman", "--",
                 python_path, "-m", "rainman", "serve"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                print("   Done: `claude mcp add rainman` registered")
            else:
                errors.append("MCP registration")
                print(f"   Warning: claude mcp add failed: {result.stderr.strip()}")
                print(f"   Run manually: claude mcp add rainman -- {python_path} -m rainman serve")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            errors.append("MCP registration")
            print(f"   Warning: could not run `claude` CLI")
            print(f"   Run manually: claude mcp add rainman -- {python_path} -m rainman serve")
    else:
        errors.append("MCP registration")
        print("   Warning: `claude` CLI not found in PATH")
        print(f"   Run manually: claude mcp add rainman -- {python_path} -m rainman serve")

    # Step 3: Configure hooks in .claude/settings.json
    print("\n3. Configuring Claude Code hooks ...")
    claude_dir = os.path.join(project_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    settings_path = os.path.join(claude_dir, "settings.json")

    hooks_config = {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{python_path} -m rainman.hooks.session_start",
            }],
        }],
        "PostCompact": [{
            "matcher": "auto",
            "hooks": [{
                "type": "command",
                "command": f"{python_path} -m rainman.hooks.post_compact",
            }],
        }],
        "PostToolUse": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{python_path} -m rainman.hooks.post_tool_use",
            }],
        }],
    }

    try:
        if os.path.exists(settings_path):
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
        else:
            settings = {}

        existing_hooks = settings.get("hooks", {})
        # Merge — don't overwrite existing hooks
        for hook_name, hook_list in hooks_config.items():
            if hook_name not in existing_hooks:
                existing_hooks[hook_name] = hook_list
            else:
                # Check if rainman hook already registered
                has_rainman = any(
                    "rainman" in h.get("command", "")
                    for entry in existing_hooks[hook_name]
                    for h in entry.get("hooks", [])
                )
                if not has_rainman:
                    existing_hooks[hook_name].extend(hook_list)

        settings["hooks"] = existing_hooks
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        print(f"   Done: {settings_path}")
    except Exception as e:
        errors.append("hooks config")
        print(f"   Warning: could not write hooks config: {e}")

    # Step 4: Create .mcp.json for project-level MCP
    print("\n4. Creating .mcp.json ...")
    mcp_path = os.path.join(project_dir, ".mcp.json")
    mcp_config = {
        "mcpServers": {
            "rainman": {
                "type": "stdio",
                "command": python_path,
                "args": ["-m", "rainman", "serve"],
            }
        }
    }
    try:
        if os.path.exists(mcp_path):
            with open(mcp_path, encoding="utf-8") as f:
                existing = json.load(f)
            if "rainman" not in existing.get("mcpServers", {}):
                existing.setdefault("mcpServers", {})["rainman"] = mcp_config["mcpServers"]["rainman"]
                with open(mcp_path, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
                print(f"   Done: added to existing {mcp_path}")
            else:
                print(f"   Skipped: rainman already in {mcp_path}")
        else:
            with open(mcp_path, "w", encoding="utf-8") as f:
                json.dump(mcp_config, f, indent=2)
            print(f"   Done: {mcp_path}")
    except Exception as e:
        errors.append(".mcp.json")
        print(f"   Warning: could not write .mcp.json: {e}")

    # Summary
    print(f"\n{'=' * 50}")
    if not errors:
        print("Setup complete! Rainman is ready.")
    else:
        print(f"Setup mostly complete. Manual steps needed for: {', '.join(errors)}")

    print("\nNext steps:")
    print("  rainman ingest --git --files    # Import project history")
    print("  rainman doctor                  # Verify everything works")
    print("  rainman recall 'your topic'     # Search your project memory")


def cmd_doctor() -> None:
    """Self-test: verify engine, storage, scoring, and integrations work."""
    import shutil
    import tempfile

    print("Rainman Doctor")
    print("=" * 50)
    passed = 0
    failed = 0
    warnings = 0

    def _pass(msg):
        nonlocal passed
        passed += 1
        print(f"  PASS  {msg}")

    def _fail(msg):
        nonlocal failed
        failed += 1
        print(f"  FAIL  {msg}")

    def _warn(msg):
        nonlocal warnings
        warnings += 1
        print(f"  WARN  {msg}")

    # Test 1: Engine — add + recall round-trip
    print("\n1. Engine ...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = os.path.join(tmpdir, "proj")
            glob = os.path.join(tmpdir, "glob")
            os.makedirs(proj)
            os.makedirs(glob)
            engine = RainmanEngine(project_dir=proj, global_dir=glob)
            engine.store.init_project(proj)
            engine.store.init_global()

            m1 = engine.add("authentication module handles JWT token validation",
                            category="pattern", tags=["auth"])
            m2 = engine.add("critical bug: login fails with expired refresh tokens",
                            category="failure")
            m3 = engine.add("database migration adds user_roles table",
                            category="decision")

            if m1.id and m2.id and m3.id:
                _pass("add() creates memories with unique IDs")
            else:
                _fail("add() did not create valid IDs")

            if m1.sentiment and m2.sentiment:
                _pass("auto-sentiment classification works")
            else:
                _fail("auto-sentiment not working")

            results = engine.recall("JWT authentication token")
            if results and "authentication" in results[0].memory.content:
                _pass(f"recall() finds correct memory (score: {results[0].total_score:.3f})")
            else:
                _fail("recall() did not find the right memory")

            if results[0].keyword_score > 0:
                _pass("keyword scoring works")
            else:
                _fail("keyword scoring returned 0")

            if results[0].recency_score > 0:
                _pass("temporal decay scoring works")
            else:
                _fail("temporal decay returned 0")

            # Auto-linking
            engine.add("authentication JWT refresh token rotation pattern")
            linked = [m for m in engine.get_all() if m.linked_ids]
            if linked:
                _pass("auto-linking detects related memories")
            else:
                _warn("auto-linking did not fire (may need more content overlap)")

    except Exception as e:
        _fail(f"engine crashed: {e}")

    # Test 2: Persistence — save + reload
    print("\n2. Persistence ...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = os.path.join(tmpdir, "proj")
            glob = os.path.join(tmpdir, "glob")
            os.makedirs(proj)
            os.makedirs(glob)

            e1 = RainmanEngine(project_dir=proj, global_dir=glob)
            e1.store.init_project(proj)
            e1.store.init_global()
            e1.add("persistent test memory about caching strategies", category="pattern")

            e2 = RainmanEngine(project_dir=proj, global_dir=glob)
            results = e2.recall("caching strategies")
            if results and "caching" in results[0].memory.content:
                _pass("memories persist to disk and reload correctly")
            else:
                _fail("memories did not survive restart")

            # Check JSON readability
            mem_path = os.path.join(proj, ".rainman", "memories.json")
            with open(mem_path, encoding="utf-8") as f:
                data = json.load(f)
            if data and "content" in data[0]:
                _pass("on-disk JSON is valid and human-readable")
            else:
                _fail("on-disk JSON is malformed")

    except Exception as e:
        _fail(f"persistence test crashed: {e}")

    # Test 3: Project setup
    print("\n3. Project setup ...")
    cwd = os.getcwd()
    rainman_dir = os.path.join(cwd, ".rainman")
    if os.path.isdir(rainman_dir):
        _pass(f".rainman/ exists at {rainman_dir}")
        mem_file = os.path.join(rainman_dir, "memories.json")
        if os.path.exists(mem_file):
            try:
                with open(mem_file, encoding="utf-8") as f:
                    data = json.load(f)
                _pass(f"memories.json has {len(data)} memories")
            except json.JSONDecodeError:
                _fail("memories.json is corrupted")
        else:
            _warn("memories.json not found — run `rainman init`")
    else:
        _warn(f".rainman/ not found in {cwd} — run `rainman init` or `rainman setup`")

    global_dir = os.path.expanduser("~/.rainman")
    if os.path.isdir(global_dir):
        _pass(f"global store exists at {global_dir}")
    else:
        _warn("global store (~/.rainman/) not found — run `rainman init`")

    # Test 4: MCP integration
    print("\n4. MCP integration ...")
    mcp_path = os.path.join(cwd, ".mcp.json")
    if os.path.exists(mcp_path):
        try:
            with open(mcp_path, encoding="utf-8") as f:
                mcp = json.load(f)
            if "rainman" in mcp.get("mcpServers", {}):
                _pass(".mcp.json has rainman server registered")
            else:
                _warn(".mcp.json exists but rainman not registered — run `rainman setup`")
        except json.JSONDecodeError:
            _fail(".mcp.json is corrupted")
    else:
        _warn(".mcp.json not found — run `rainman setup` to create it")

    # Test 5: Hooks
    print("\n5. Hooks ...")
    settings_path = os.path.join(cwd, ".claude", "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
            hooks = settings.get("hooks", {})
            hook_count = 0
            for hook_name, hook_list in hooks.items():
                for entry in hook_list:
                    for h in entry.get("hooks", []):
                        if "rainman" in h.get("command", ""):
                            hook_count += 1
            if hook_count > 0:
                _pass(f"{hook_count} rainman hook(s) configured in .claude/settings.json")
            else:
                _warn("no rainman hooks found in .claude/settings.json — run `rainman setup`")
        except json.JSONDecodeError:
            _fail(".claude/settings.json is corrupted")
    else:
        _warn(".claude/settings.json not found — run `rainman setup` to configure hooks")

    # Test 6: Claude CLI
    print("\n6. Claude CLI ...")
    claude_path = shutil.which("claude")
    if claude_path:
        _pass(f"claude CLI found at {claude_path}")
    else:
        _warn("claude CLI not in PATH — MCP server registration needs manual setup")

    # Summary
    print(f"\n{'=' * 50}")
    total = passed + failed + warnings
    print(f"Results: {passed} passed, {failed} failed, {warnings} warnings")
    if failed == 0:
        print("Rainman is healthy!")
    else:
        print("Fix the failures above, then run `rainman doctor` again.")
