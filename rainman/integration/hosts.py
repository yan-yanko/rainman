"""Registry of MCP-capable AI coding hosts and how to configure each.

Rainman's MCP server (``python -m rainman serve``) speaks standard MCP, so any
MCP-capable editor can use its tools (recall / remember / context / links /
status). This maps each host to the config file + JSON shape it expects, so we
can print a ready-to-paste snippet (``rainman mcp-config``) or write the
project-local ones (``rainman setup --host X``). stdlib only.

Auto-surfacing note: Claude Code additionally supports *hooks* (inject at
session start, learn from edits) — that PUSH path is host-specific. Every other
host here gets the PULL path: the model calls the recall/remember tools itself.
The git post-commit hook (`rainman learn-commit`) covers auto-learn everywhere.
"""

import json
import os

_CMD = "python"
_ARGS = ["-m", "rainman", "serve"]


def _entry(style):
    if style == "typed":   # Claude Code: explicit stdio type
        return {"type": "stdio", "command": _CMD, "args": list(_ARGS)}
    if style == "zed":     # Zed nests the command
        return {"command": {"path": _CMD, "args": list(_ARGS)}}
    return {"command": _CMD, "args": list(_ARGS)}  # cursor/vscode/windsurf/cline/continue/generic


# key -> spec. ``scope="project"`` hosts have a repo-local config file we can
# safely write; ``scope="global"`` hosts we only print (editing a user-global
# file automatically is too surprising).
HOSTS = {
    "claude": {
        "display": "Claude Code",
        "path": ".mcp.json",
        "wrapper": "mcpServers",
        "style": "typed",
        "scope": "project",
        "note": "Or run: claude mcp add rainman -- python -m rainman serve. "
                "Claude Code also supports hooks — use `rainman setup` for full auto-surfacing.",
    },
    "cursor": {
        "display": "Cursor",
        "path": ".cursor/mcp.json",
        "wrapper": "mcpServers",
        "style": "plain",
        "scope": "project",
        "note": "Global alternative: ~/.cursor/mcp.json. Tools are pull-based (the model calls them).",
    },
    "vscode": {
        "display": "VS Code (GitHub Copilot agent)",
        "path": ".vscode/mcp.json",
        "wrapper": "servers",
        "style": "plain",
        "scope": "project",
        "note": "Open Copilot Chat -> Agent mode -> Rainman tools available.",
    },
    "windsurf": {
        "display": "Windsurf",
        "path": "~/.codeium/windsurf/mcp_config.json",
        "wrapper": "mcpServers",
        "style": "plain",
        "scope": "global",
        "note": "Windsurf -> Settings -> MCP, or edit that file directly.",
    },
    "cline": {
        "display": "Cline (VS Code)",
        "path": "cline_mcp_settings.json (Cline -> MCP Servers -> Configure)",
        "wrapper": "mcpServers",
        "style": "plain",
        "scope": "global",
        "note": "Cline stores this in the extension's global storage.",
    },
    "zed": {
        "display": "Zed",
        "path": "Zed settings.json (context_servers)",
        "wrapper": "context_servers",
        "style": "zed",
        "scope": "global",
        "note": "Zed -> Settings, add under context_servers.",
    },
    "continue": {
        "display": "Continue",
        "path": "~/.continue/config.yaml (mcpServers)",
        "wrapper": "mcpServers",
        "style": "plain",
        "scope": "global",
        "note": "Continue's config is YAML; this JSON maps 1:1 — see docs.continue.dev/customize/tools.",
    },
    "generic": {
        "display": "Generic MCP client",
        "path": "(your client's MCP config file)",
        "wrapper": "mcpServers",
        "style": "plain",
        "scope": "global",
        "note": "Most MCP clients use exactly this shape.",
    },
}


def known_hosts():
    return list(HOSTS.keys())


def snippet(host_key):
    """The JSON config object for a host."""
    spec = HOSTS[host_key]
    return {spec["wrapper"]: {"rainman": _entry(spec["style"])}}


def snippet_text(host_key):
    return json.dumps(snippet(host_key), indent=2)


def is_project_local(host_key):
    return HOSTS.get(host_key, {}).get("scope") == "project"


def merge_into(path, host_key):
    """Merge the rainman server entry into a JSON config at ``path`` (creating
    it if missing). Never touches other servers. Returns a status string."""
    spec = HOSTS[host_key]
    wrapper = spec["wrapper"]
    entry = _entry(spec["style"])
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        servers = data.setdefault(wrapper, {})
        if "rainman" in servers:
            return f"skipped (rainman already present): {path}"
        servers["rainman"] = entry
    else:
        data = {wrapper: {"rainman": entry}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return f"wrote: {path}"
