"""Host-agnostic integration layer.

Rainman's core (store, scoring, recall) never knew about any AI coding host.
This package is the *behaviour* layer that used to live inside the Claude Code
hooks — expressed independent of any one host — plus a registry of how each
MCP-capable host is configured.

  core.py   the automatic behaviours (load context, re-inject after compaction,
            learn from a tool action, capture learnings, learn from a commit),
            each taking a plain engine + normalised args. Zero host coupling.
  hosts.py  registry of MCP-capable editors and how to configure each.

Host adapters (the Claude Code hooks in ``rainman/hooks/``, the git post-commit
hook, ...) normalise their native event into these calls. Still zero LLM calls.

Submodules are imported explicitly (``from rainman.integration import core``)
to keep package import cheap and free of ordering coupling.
"""
