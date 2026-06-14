"""
Rainman MCP Server
===================

Model Context Protocol server over stdio (JSON-RPC 2.0).
Provides 5 tools: recall, remember, context, links, status.

Register with Claude Code:
    claude mcp add rainman -- python -m rainman serve

Or in .mcp.json:
    {
        "mcpServers": {
            "rainman": {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "rainman", "serve"]
            }
        }
    }
"""

import json
import os
import sys
from typing import Any, Dict, Optional

from rainman.core.engine import RainmanEngine
from rainman.core.log import get_logger


log = get_logger(__name__)

# MCP Protocol version
PROTOCOL_VERSION = "2024-11-05"

# Tool definitions
TOOLS = [
    {
        "name": "recall",
        "description": (
            "Search project memory for relevant knowledge. Use when you need to find "
            "existing solutions, past decisions, known patterns, or previous failures. "
            "ALWAYS use this before declaring a problem unsolvable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for (e.g., 'voting bias', 'auth pattern', 'database migration')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 5)",
                    "default": 5,
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category",
                    "enum": ["pattern", "solution", "failure", "decision", "convention", "note"],
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Files you're currently working on. Memories about these files "
                        "(esp. past failures/fixes) are surfaced even if the query doesn't "
                        "lexically match them."
                    ),
                },
                "error": {
                    "type": "string",
                    "description": (
                        "A recent error message / stack trace. Surfaces the experience card "
                        "for this exact failure if one was captured before."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Store a new learning in project memory. Use when you discover something "
            "important: a fix that worked, a decision made, a pattern found, a failure "
            "to avoid. This persists across sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The knowledge to remember",
                },
                "category": {
                    "type": "string",
                    "description": "Category of knowledge",
                    "enum": ["pattern", "solution", "failure", "decision", "convention", "note"],
                    "default": "note",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for retrieval (e.g., ['election', 'bias'])",
                },
                "file_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Related file paths",
                },
                "global": {
                    "type": "boolean",
                    "description": "Store in global layer (cross-project) instead of project",
                    "default": False,
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "context",
        "description": (
            "Get current working context — recent and high-importance memories. "
            "Use at the start of a session or when you need orientation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max memories to return (default: 10)",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "links",
        "description": (
            "Find all memories linked to a specific file or concept. "
            "Use when working on a file to see what's known about it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "File path or concept to search for",
                },
            },
            "required": ["ref"],
        },
    },
    {
        "name": "status",
        "description": "Show memory statistics: count by category, layer, sentiment, top tags.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class RainmanMCPServer:
    """MCP server over stdio."""

    def __init__(self):
        project_dir = os.environ.get("RAINMAN_PROJECT", os.getcwd())
        self.engine = RainmanEngine(project_dir=project_dir)

    def handle_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle a single JSON-RPC message."""
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            return self._response(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "rainman",
                    "version": "0.1.0",
                },
            })

        elif method == "notifications/initialized":
            # Client acknowledgment — no response needed
            return None

        elif method == "tools/list":
            return self._response(msg_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            args = params.get("arguments", {})
            result = self._call_tool(tool_name, args)
            return self._response(msg_id, result)

        elif method == "ping":
            return self._response(msg_id, {})

        else:
            # JSON-RPC 2.0: don't respond to notifications (no id)
            if msg_id is None:
                return None
            return self._error(msg_id, -32601, f"Unknown method: {method}")

    def _call_tool(self, name: str, args: Dict[str, Any]) -> Dict:
        """Execute a tool and return MCP-formatted result."""
        try:
            if name == "recall":
                if "query" not in args or not args["query"]:
                    return self._tool_error("recall requires 'query' argument")
                query = str(args["query"])[:500]
                limit = max(1, min(50, int(args.get("limit", 5))))
                raw_files = args.get("files") or []
                context_files = [str(f)[:500] for f in raw_files[:20]] if isinstance(raw_files, list) else None
                error_signature = str(args["error"])[:1000] if args.get("error") else None
                results = self.engine.recall(
                    query=query,
                    limit=limit,
                    category=args.get("category"),
                    context_files=context_files or None,
                    error_signature=error_signature,
                )
                text = self._format_recall(results)

            elif name == "remember":
                if "content" not in args or not args["content"]:
                    return self._tool_error("remember requires 'content' argument")
                m = self.engine.add(
                    content=args["content"],
                    category=args.get("category", "note"),
                    tags=args.get("tags", []),
                    file_refs=args.get("file_refs", []),
                    source="mcp",
                    layer="global" if args.get("global") else "project",
                )
                text = f"Remembered [{m.category}]: {m.content[:100]}\nID: {m.id}"

            elif name == "context":
                results = self.engine.context(limit=args.get("limit", 10))
                text = self._format_context(results)

            elif name == "links":
                if "ref" not in args or not args["ref"]:
                    return self._tool_error("links requires 'ref' argument")
                results = self.engine.links(args["ref"])
                text = self._format_links(args["ref"], results)

            elif name == "status":
                stats = self.engine.get_stats()
                text = self._format_stats(stats)

            else:
                return self._tool_error(f"Unknown tool: {name}")

            return {"content": [{"type": "text", "text": text}]}

        except Exception:
            # Don't leak internals (paths, stack details) back to the model.
            # Full diagnostics go to the server log only.
            log.exception("tool %r failed", name)
            return self._tool_error("internal error executing tool")

    def _tool_error(self, message: str) -> Dict:
        """Return a structured MCP tool error."""
        return {
            "content": [{"type": "text", "text": f"Error: {message}"}],
            "isError": True,
        }

    def _format_recall(self, results) -> str:
        if not results:
            return "No memories found."
        lines = [f"Found {len(results)} memories:\n"]
        for i, r in enumerate(results, 1):
            m = r.memory
            lines.append(f"{i}. [{m.category}] {m.content}")
            lines.append(
                f"   score={r.total_score:.3f} layer={m.layer} "
                f"trust={m.trust} source={m.source or 'unknown'}"
            )
            if m.file_refs:
                lines.append(f"   files: {', '.join(m.file_refs)}")
            if m.tags:
                lines.append(f"   tags: {', '.join(m.tags)}")
        return "\n".join(lines)

    def _format_context(self, results) -> str:
        if not results:
            return "No memories yet."
        lines = ["Current context:\n"]
        for i, r in enumerate(results, 1):
            m = r.memory
            lines.append(f"{i}. [{m.category}] {m.content}")
        return "\n".join(lines)

    def _format_links(self, ref, results) -> str:
        if not results:
            return f"No memories linked to '{ref}'"
        lines = [f"Memories linked to '{ref}':\n"]
        for i, m in enumerate(results, 1):
            lines.append(f"{i}. [{m.category}] {m.content}")
            if m.file_refs:
                lines.append(f"   files: {', '.join(m.file_refs)}")
        return "\n".join(lines)

    def _format_stats(self, stats) -> str:
        lines = [
            f"Total memories: {stats['total']}",
            f"By layer: {json.dumps(stats['by_layer'])}",
            f"By category: {json.dumps(stats['by_category'])}",
        ]
        if stats["top_tags"]:
            lines.append(f"Top tags: {', '.join(t for t, _ in stats['top_tags'][:5])}")
        return "\n".join(lines)

    def _response(self, msg_id, result) -> Dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _error(self, msg_id, code, message) -> Dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def run_server():
    """Main loop: read JSON-RPC from stdin, write responses to stdout."""
    server = RainmanMCPServer()

    # Ensure stdout is line-buffered for stdio transport
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = server.handle_message(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
