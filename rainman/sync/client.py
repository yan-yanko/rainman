"""
Sync client
===========

Pushes/pulls memories to a self-hosted sync server using the monotonic-cursor
delta protocol. Stdlib only (``urllib``). Two modes:

  * team (default)     — the repo's PROJECT-layer memories, shared with the
                         team workspace. State in
                         ``<project>/.rainman/sync_state.json`` (committable;
                         contains no secret).
  * personal (opt-in)  — the GLOBAL layer (your personal cross-project
                         memory), roamed across your own machines via a
                         personal workspace. State in
                         ``~/.rainman/personal_sync.json`` — never the repo,
                         and never mixed with a team workspace.

The bearer token comes from ``RAINMAN_SYNC_TOKEN`` or
``~/.rainman/sync_credentials.json`` ({remote_url: token}) — NEVER the repo.

Conflict resolution is last-write-to-server-wins by server ``seq``; the local
audit log preserves history. Pulled memories overwrite local copies (including
rehearsal stats) — acceptable for shared team knowledge in v1.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from rainman.core.models import Memory
from rainman.core.log import get_logger

log = get_logger(__name__)

# Must mirror the server's hash definition (volatile rehearsal stats excluded).
_VOLATILE = ("recall_count", "last_recalled")


class SyncError(Exception):
    """A recoverable sync failure (network, auth, config)."""


def _content_hash(data: dict) -> str:
    stable = {k: v for k, v in data.items() if k not in _VOLATILE}
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class SyncClient:
    def __init__(self, engine, personal: bool = False):
        self.engine = engine
        self.personal = personal
        self._layer = "global" if personal else "project"
        if personal:
            # Personal memory roams via ~/.rainman — nothing touches the repo.
            self._state_path = os.path.join(engine.store.global_dir(), "personal_sync.json")
        else:
            proj = engine.store._project_dir
            if not proj:
                raise SyncError("team sync requires a project (.rainman/) directory")
            self._state_path = os.path.join(proj, "sync_state.json")
        self._creds_path = os.path.join(engine.store.global_dir(), "sync_credentials.json")

    # ── Config / state ───────────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict) -> None:
        os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def configure(self, remote: str, workspace: str, token: Optional[str] = None) -> None:
        state = self._load_state()
        state["remote"] = remote.rstrip("/")
        state["workspace"] = workspace
        state.setdefault("last_pull_seq", 0)
        state.setdefault("pushed", {})
        self._save_state(state)
        if token:
            self._store_token(state["remote"], token)

    def is_configured(self) -> bool:
        state = self._load_state()
        return bool(state.get("remote") and state.get("workspace"))

    def describe(self) -> dict:
        state = self._load_state()
        return {
            "remote": state.get("remote"),
            "workspace": state.get("workspace"),
            "last_pull_seq": state.get("last_pull_seq", 0),
            "token_present": bool(self._token(state.get("remote", ""))),
        }

    # ── Token (kept out of the repo) ─────────────────────────────

    def _store_token(self, remote: str, token: str) -> None:
        creds = {}
        if os.path.exists(self._creds_path):
            try:
                with open(self._creds_path, encoding="utf-8") as f:
                    creds = json.load(f)
            except (OSError, ValueError):
                creds = {}
        creds[remote] = token
        os.makedirs(os.path.dirname(self._creds_path), exist_ok=True)
        with open(self._creds_path, "w", encoding="utf-8") as f:
            json.dump(creds, f, indent=2)

    def _token(self, remote: str) -> Optional[str]:
        env = os.environ.get("RAINMAN_SYNC_TOKEN", "").strip()
        if env:
            return env
        try:
            with open(self._creds_path, encoding="utf-8") as f:
                return json.load(f).get(remote)
        except (OSError, ValueError):
            return None

    # ── HTTP ─────────────────────────────────────────────────────

    def _request(self, method: str, remote: str, path: str,
                 token: str, body: Optional[dict] = None) -> dict:
        url = remote.rstrip("/") + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise SyncError(f"server returned {e.code} {e.reason}")
        except urllib.error.URLError as e:
            raise SyncError(f"could not reach {url}: {e.reason}")

    # ── Sync ─────────────────────────────────────────────────────

    def _ready(self):
        state = self._load_state()
        remote, ws = state.get("remote"), state.get("workspace")
        if not remote or not ws:
            flag = " --personal" if self.personal else ""
            raise SyncError(
                f"no remote configured — run `rainman remote add <url> <workspace>{flag}`")
        token = self._token(remote)
        if not token:
            raise SyncError("no token — set RAINMAN_SYNC_TOKEN or pass --token to `rainman remote add`")
        return state, remote, ws, token

    def pull(self) -> int:
        state, remote, ws, token = self._ready()
        since = state.get("last_pull_seq", 0)
        resp = self._request("GET", remote, f"/v1/workspaces/{ws}/pull?since={since}", token)
        changes: List[dict] = resp.get("changes", [])
        # `pushed` is the synced baseline — updated by pull too, so memories we
        # received from the server aren't mistaken for local-originals and
        # re-uploaded (which would resurrect another client's deletion).
        pushed: Dict[str, str] = state.get("pushed", {})
        applied = self._apply(changes, pushed)
        state["pushed"] = pushed
        state["last_pull_seq"] = resp.get("cursor", since)
        self._save_state(state)
        return applied

    def _apply(self, changes: List[dict], pushed: Dict[str, str]) -> int:
        if not changes:
            return 0
        # Rebuild the full set once and rewrite — avoids cache/save hazards.
        by_id: Dict[str, Memory] = {m.id: m for m in self.engine.store.load_all()}
        applied = 0
        for ch in changes:
            mid = ch.get("id")
            if ch.get("deleted"):
                pushed.pop(mid, None)
                if by_id.pop(mid, None) is not None:
                    applied += 1
            elif ch.get("data"):
                m = Memory.from_dict(ch["data"])
                m.layer = self._layer
                by_id[m.id] = m
                pushed[mid] = _content_hash(ch["data"])
                applied += 1
        self.engine.store.save_all(list(by_id.values()))
        self.engine._loaded = False  # invalidate any cached working set
        return applied

    def push(self) -> dict:
        state, remote, ws, token = self._ready()
        pushed: Dict[str, str] = state.get("pushed", {})
        local = [m for m in self.engine.store.load_all() if m.layer == self._layer]

        changed, local_ids = [], set()
        for m in local:
            local_ids.add(m.id)
            d = m.to_dict()
            if pushed.get(m.id) != _content_hash(d):
                changed.append(d)
        deletions = [mid for mid in pushed if mid not in local_ids]

        if not changed and not deletions:
            return {"pushed": 0, "deleted": 0}

        self._request("POST", remote, f"/v1/workspaces/{ws}/push", token,
                      body={"memories": changed, "deletions": deletions})

        for d in changed:
            pushed[d["id"]] = _content_hash(d)
        for mid in deletions:
            pushed.pop(mid, None)
        state["pushed"] = pushed
        self._save_state(state)
        return {"pushed": len(changed), "deleted": len(deletions)}

    def sync(self) -> dict:
        """Push local changes, then pull remote ones.

        Push must come first so a local deletion (derived from the ``pushed``
        set minus the current local set) is emitted as a tombstone *before* a
        pull could otherwise re-fetch and resurrect the just-deleted memory.
        """
        pushed = self.push()
        pulled = self.pull()
        return {"pulled": pulled, **pushed}
