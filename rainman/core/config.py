"""
Policy control plane
====================

Org-managed configuration with a three-layer precedence chain so a security
team can distribute mandates that developers can't quietly relax.

Layers & locations (all optional — absent means "today's behavior"):

  * org     — JSON at ``RAINMAN_ORG_POLICY`` env path, else the platform
              system path (``%PROGRAMDATA%\\rainman\\policy.json`` on Windows,
              ``/etc/rainman/policy.json`` on POSIX). MDM/config-mgmt
              distributable. Has two blocks:
                  {"enforce": {...}, "defaults": {...}}
  * project — ``<project>/.rainman/config.json`` (git-committable)
  * user    — ``~/.rainman/config.json``

Per-key resolution (first hit wins):
    org.enforce  >  project  >  user  >  org.defaults  >  built-in default

``enforce`` keys are mandates — lower layers cannot override them. ``defaults``
keys are suggestions the org provides but project/user may override.

Zero external deps. Reads are best-effort: a missing/garbled file is ignored,
never fatal — policy must not be able to brick the tool.
"""

import json
import os
import sys
from typing import Any, Dict, Optional

from rainman.core.log import get_logger

log = get_logger(__name__)


# Built-in defaults == current behavior. Every key is optional everywhere.
DEFAULTS: Dict[str, Any] = {
    "audit": False,                    # enable the append-only audit log
    "disable_auto_learn": False,       # turn off post_tool_use / session_end learning
    "disable_global_layer": False,     # ignore ~/.rainman global memories
    "auto_inject_min_trust": "hook",   # trust floor for unsolicited SessionStart injection
    "recall_min_trust": None,          # trust floor for explicit recall (None = no gate)
    "quarantine_ingest": False,        # ingested memories not recallable until reviewed
    "extra_redaction_patterns": [],    # additional regexes redaction must apply
    "path_denylist": [],               # extra path substrings auto-learn must skip
    "category_denylist": [],           # categories that may not be stored
    "retention_days": None,            # TTL prune (enforced in Phase 1d)
    "storage_backend": "json",         # "json" | "sqlite" — switch via `rainman migrate`
}


def _read_json(path: str) -> Dict[str, Any]:
    """Best-effort JSON read. Returns {} on any problem."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        if os.path.exists(path):
            log.warning("ignoring unreadable policy file %s: %s", path, e)
        return {}


def _org_policy_path() -> Optional[str]:
    override = os.environ.get("RAINMAN_ORG_POLICY", "").strip()
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(base, "rainman", "policy.json")
    return "/etc/rainman/policy.json"


class Policy:
    """Resolved policy with org-enforced mandates layered over defaults."""

    def __init__(self, enforce: Dict[str, Any], project: Dict[str, Any],
                 user: Dict[str, Any], org_defaults: Dict[str, Any]):
        self._enforce = enforce or {}
        self._project = project or {}
        self._user = user or {}
        self._org_defaults = org_defaults or {}

    def get(self, key: str) -> Any:
        """Resolve a policy key: enforce > project > user > org.defaults > builtin."""
        for layer in (self._enforce, self._project, self._user, self._org_defaults):
            if key in layer:
                return layer[key]
        return DEFAULTS.get(key)

    def locked(self, key: str) -> bool:
        """True if the org enforces this key (lower layers can't override)."""
        return key in self._enforce

    def explain(self) -> Dict[str, Dict[str, Any]]:
        """Effective value + provenance for every policy key.

        The governance report behind ``rainman policy``: for each known key
        (and any extra key present in a layer), which layer decided the
        effective value and whether the org has locked it. Lets an admin or
        auditor answer "what is this machine actually running under, and why"
        without reading four files.
        """
        layers = (
            ("org.enforce", self._enforce),
            ("project", self._project),
            ("user", self._user),
            ("org.defaults", self._org_defaults),
        )
        keys = list(DEFAULTS)
        for _, layer in layers:
            for k in layer:
                if k not in keys:
                    keys.append(k)

        report: Dict[str, Dict[str, Any]] = {}
        for key in keys:
            source, value = "builtin", DEFAULTS.get(key)
            for name, layer in layers:
                if key in layer:
                    source, value = name, layer[key]
                    break
            report[key] = {"value": value, "source": source, "locked": self.locked(key)}
        return report


def load_policy(project_dir: Optional[str] = None,
                global_dir: Optional[str] = None) -> Policy:
    """Load and merge org / project / user policy layers."""
    org_raw = _read_json(_org_policy_path())
    enforce = org_raw.get("enforce", {}) if isinstance(org_raw.get("enforce"), dict) else {}
    org_defaults = org_raw.get("defaults", {}) if isinstance(org_raw.get("defaults"), dict) else {}

    project = {}
    if project_dir:
        project = _read_json(os.path.join(project_dir, ".rainman", "config.json"))

    user = {}
    if global_dir:
        user = _read_json(os.path.join(global_dir, "config.json"))

    return Policy(enforce=enforce, project=project, user=user, org_defaults=org_defaults)
