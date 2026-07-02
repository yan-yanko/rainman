"""
Rainman CLI Entry Point
========================

Usage:
    rainman init                          Initialize .rainman/ in current directory
    rainman add "content" [options]       Add a memory
    rainman recall "query" [options]      Search memories
    rainman status                        Show memory stats
    rainman links <ref>                   Show linked memories
    rainman context                       Show current working context
    rainman export                        Dump all memories as JSON
    rainman serve                         Start MCP stdio server
"""

import argparse
import sys


def main():
    # CLI commands print memory content, which may be non-ASCII (e.g. Hebrew);
    # Windows' default cp1252 stdout would crash on it. Force UTF-8 first.
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()

    parser = argparse.ArgumentParser(
        prog="rainman",
        description="Context-aware project memory for AI coding tools",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize .rainman/ in current directory")
    p_init.add_argument("--dir", help="Project directory (default: cwd)")

    # add
    p_add = sub.add_parser("add", help="Add a memory")
    p_add.add_argument("content", help="Memory content")
    p_add.add_argument("--category", "-c", default="note",
                        choices=["pattern", "solution", "failure", "decision", "convention", "note"])
    p_add.add_argument("--tag", "-t", action="append", dest="tags", default=[])
    p_add.add_argument("--file", "-f", action="append", dest="file_refs", default=[])
    p_add.add_argument("--global", dest="is_global", action="store_true",
                        help="Store in global layer instead of project")

    # recall
    p_recall = sub.add_parser("recall", help="Search memories by query")
    p_recall.add_argument("query", help="Search query")
    p_recall.add_argument("--limit", "-n", type=int, default=5)
    p_recall.add_argument("--category", "-c")

    # status
    sub.add_parser("status", help="Show memory statistics")

    # links
    p_links = sub.add_parser("links", help="Show memories linked to a file or concept")
    p_links.add_argument("ref", help="File path or concept to search for")

    # context
    p_context = sub.add_parser("context", help="Show current working context")
    p_context.add_argument("--limit", "-n", type=int, default=10)

    # export
    sub.add_parser("export", help="Dump all memories as JSON")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest git history and/or file structure")
    p_ingest.add_argument("--git", action="store_true", help="Parse git log into memories")
    p_ingest.add_argument("--files", action="store_true", help="Scan project files into memories")
    p_ingest.add_argument("--limit", "-n", type=int, default=50, help="Max git commits (default: 50)")
    p_ingest.add_argument("--depth", type=int, default=4, help="Max directory depth for files (default: 4)")

    # migrate
    p_migrate = sub.add_parser("migrate", help="Migrate store between backends (json <-> sqlite)")
    p_migrate.add_argument("--to", required=True, choices=["json", "sqlite"], help="Target backend")

    # remote
    p_remote = sub.add_parser("remote", help="Configure the sync remote for this project")
    p_remote.add_argument("action", choices=["add", "show"])
    p_remote.add_argument("url", nargs="?", help="Sync server URL (for add)")
    p_remote.add_argument("workspace", nargs="?", help="Workspace id (for add)")
    p_remote.add_argument("--token", help="Per-seat bearer token (stored outside the repo)")

    # sync
    sub.add_parser("sync", help="Pull + push project memories with the sync server")

    # review
    p_review = sub.add_parser("review", help="Review quarantined memories (list/approve/reject)")
    p_review.add_argument("action", nargs="?", choices=["list", "approve", "reject"], default="list")
    p_review.add_argument("memory_id", nargs="?", help="Memory id (for approve/reject)")

    # setup
    p_setup = sub.add_parser("setup", help="One-command setup: init + MCP + hooks")
    p_setup.add_argument("--host", help="Target host (claude, cursor, vscode, "
                         "windsurf, cline, zed, continue). Default: claude (full hooks).")

    # mcp-config
    p_mcp = sub.add_parser("mcp-config", help="Print the MCP config snippet for a host")
    p_mcp.add_argument("--host", help="Host name (omit to list supported hosts)")

    # doctor
    sub.add_parser("doctor", help="Self-test: verify engine, storage, and integrations")

    # serve
    sub.add_parser("serve", help="Start MCP stdio server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Import here to keep startup fast
    from rainman.cli.commands import (
        cmd_init, cmd_add, cmd_recall, cmd_status,
        cmd_links, cmd_export, cmd_context, cmd_ingest,
        cmd_setup, cmd_doctor, cmd_review, cmd_migrate,
        cmd_remote, cmd_sync, cmd_mcp_config,
    )

    if args.command == "init":
        cmd_init(project_dir=args.dir)
    elif args.command == "add":
        cmd_add(
            content=args.content,
            category=args.category,
            tags=args.tags,
            file_refs=args.file_refs,
            is_global=args.is_global,
        )
    elif args.command == "recall":
        cmd_recall(query=args.query, limit=args.limit, category=args.category)
    elif args.command == "status":
        cmd_status()
    elif args.command == "links":
        cmd_links(ref=args.ref)
    elif args.command == "context":
        cmd_context(limit=args.limit)
    elif args.command == "export":
        cmd_export()
    elif args.command == "ingest":
        cmd_ingest(git=args.git, files=args.files, limit=args.limit, depth=args.depth)
    elif args.command == "migrate":
        cmd_migrate(to=args.to)
    elif args.command == "remote":
        cmd_remote(action=args.action, url=args.url, workspace=args.workspace, token=args.token)
    elif args.command == "sync":
        cmd_sync()
    elif args.command == "review":
        cmd_review(action=args.action, memory_id=args.memory_id)
    elif args.command == "setup":
        cmd_setup(host=args.host)
    elif args.command == "mcp-config":
        cmd_mcp_config(host=args.host)
    elif args.command == "doctor":
        cmd_doctor()
    elif args.command == "serve":
        from rainman.mcp.server import run_server
        run_server()


if __name__ == "__main__":
    main()
