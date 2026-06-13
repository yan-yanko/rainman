"""
Layered JSON Persistence
=========================

Two-layer storage: global (~/.rainman/) + project (.rainman/).
Project memories get a 1.2x boost on recall.

JSON files, human-readable, git-committable.
No database. No server.

Multi-process safety: all writes use lockfile + reload-before-write
to prevent clobbering between hooks and MCP server.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from rainman.core.log import get_logger
from rainman.core.models import Memory


log = get_logger(__name__)


# Default directories
GLOBAL_DIR = os.path.join(str(Path.home()), ".rainman")
PROJECT_DIR_NAME = ".rainman"

# Memory record schema version. Bump when Memory.to_dict/from_dict changes
# shape in a way that needs migrating older stores. Stamped into config.json
# (not memories.json, which stays a bare array its readers depend on) so a
# future loader can detect and migrate. 1 == the format shipped today.
SCHEMA_VERSION = 1

# Lock settings
LOCK_TIMEOUT = 5.0  # seconds
LOCK_RETRY_INTERVAL = 0.05  # seconds
LOCK_STALE_AGE = 30.0  # seconds — stale lock TTL


class MemoryStore:
    """Layered memory persistence: global + project."""

    def __init__(
        self,
        project_dir: Optional[str] = None,
        global_dir: Optional[str] = None,
    ):
        self._global_dir = global_dir or GLOBAL_DIR
        self._project_dir = (
            os.path.join(project_dir, PROJECT_DIR_NAME)
            if project_dir
            else None
        )

    # ── Public API ──────────────────────────────────────────────

    def audit_path(self) -> str:
        """Path of the append-only audit log (project layer if present)."""
        base = self._project_dir if self._project_dir else self._global_dir
        return os.path.join(base, "audit.log")

    def global_dir(self) -> str:
        """Resolved global-layer directory."""
        return self._global_dir

    def load_all(self) -> List[Memory]:
        """Load memories from both layers."""
        memories = []

        # Global layer
        global_path = os.path.join(self._global_dir, "memories.json")
        memories.extend(self._load_file(global_path, layer="global"))

        # Project layer
        if self._project_dir:
            project_path = os.path.join(self._project_dir, "memories.json")
            memories.extend(self._load_file(project_path, layer="project"))

        return memories

    def save_all(self, memories: List[Memory]) -> None:
        """Save memories to their respective layers."""
        global_memories = [m for m in memories if m.layer == "global"]
        project_memories = [m for m in memories if m.layer == "project"]

        # Save global
        global_path = os.path.join(self._global_dir, "memories.json")
        self._locked_save(global_path, global_memories)

        # Save project
        if self._project_dir:
            project_path = os.path.join(self._project_dir, "memories.json")
            self._locked_save(project_path, project_memories)

    def save_one(self, memory: Memory) -> None:
        """Append or update a single memory in the appropriate layer (locked)."""
        if memory.layer == "global":
            path = os.path.join(self._global_dir, "memories.json")
        elif self._project_dir:
            path = os.path.join(self._project_dir, "memories.json")
        else:
            # No project dir, fall back to global
            memory.layer = "global"
            path = os.path.join(self._global_dir, "memories.json")

        def _merge(existing: List[Memory]) -> List[Memory]:
            # Update in-place if memory already exists, else append
            for i, m in enumerate(existing):
                if m.id == memory.id:
                    existing[i] = memory
                    return existing
            existing.append(memory)
            return existing

        self._locked_read_modify_write(path, memory.layer, _merge)

    def save_layers(self, memories: List[Memory], layers: set) -> None:
        """Save only the specified layers. Avoids full rewrite on recall."""
        if "global" in layers:
            global_memories = [m for m in memories if m.layer == "global"]
            global_path = os.path.join(self._global_dir, "memories.json")
            self._locked_save(global_path, global_memories)

        if "project" in layers and self._project_dir:
            project_memories = [m for m in memories if m.layer == "project"]
            project_path = os.path.join(self._project_dir, "memories.json")
            self._locked_save(project_path, project_memories)

    def update_rehearsal_stats(self, updates: Dict[str, dict], layer: str) -> None:
        """
        Update recall_count and last_recalled for specific memory IDs.
        Locked delta operation — doesn't require full snapshot.
        """
        if layer == "global":
            path = os.path.join(self._global_dir, "memories.json")
        elif self._project_dir:
            path = os.path.join(self._project_dir, "memories.json")
        else:
            return

        def _apply_stats(existing: List[Memory]) -> List[Memory]:
            for m in existing:
                if m.id in updates:
                    m.recall_count = updates[m.id].get("recall_count", m.recall_count)
                    m.last_recalled = updates[m.id].get("last_recalled", m.last_recalled)
            return existing

        self._locked_read_modify_write(path, layer, _apply_stats)

    def init_project(self, project_dir: str) -> str:
        """Initialize .rainman/ in a project directory."""
        target = os.path.join(project_dir, PROJECT_DIR_NAME)
        os.makedirs(target, exist_ok=True)

        memories_path = os.path.join(target, "memories.json")
        if not os.path.exists(memories_path):
            self._save_file(memories_path, [])

        config_path = os.path.join(target, "config.json")
        if not os.path.exists(config_path):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"version": "0.1.0", "schema_version": SCHEMA_VERSION, "project": ""},
                    f,
                    indent=2,
                )

        self._project_dir = target
        return target

    def schema_version(self, layer: str = "project") -> Optional[int]:
        """Return the stored memory schema version for a layer.

        Returns None for legacy stores written before versioning (config
        missing or without the key) — the signal a migration may be needed.
        """
        base = self._project_dir if layer == "project" else self._global_dir
        if not base:
            return None
        config_path = os.path.join(base, "config.json")
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f).get("schema_version")
        except (OSError, ValueError):
            return None

    def init_global(self) -> str:
        """Initialize ~/.rainman/ global store."""
        os.makedirs(self._global_dir, exist_ok=True)

        memories_path = os.path.join(self._global_dir, "memories.json")
        if not os.path.exists(memories_path):
            self._save_file(memories_path, [])

        config_path = os.path.join(self._global_dir, "config.json")
        if not os.path.exists(config_path):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"version": "0.1.0", "schema_version": SCHEMA_VERSION}, f, indent=2
                )

        return self._global_dir

    def get_stats(self) -> Dict:
        """Return stats across both layers."""
        memories = self.load_all()
        by_category = {}
        by_layer = {"global": 0, "project": 0}
        by_sentiment = {}
        all_tags = {}

        for m in memories:
            by_category[m.category] = by_category.get(m.category, 0) + 1
            by_layer[m.layer] = by_layer.get(m.layer, 0) + 1
            by_sentiment[m.sentiment] = by_sentiment.get(m.sentiment, 0) + 1
            for t in m.tags:
                all_tags[t] = all_tags.get(t, 0) + 1

        return {
            "total": len(memories),
            "by_category": by_category,
            "by_layer": by_layer,
            "by_sentiment": by_sentiment,
            "top_tags": sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10],
        }

    # ── Locking ──────────────────────────────────────────────────

    def _acquire_lock(self, path: str) -> str:
        """
        Acquire an exclusive lockfile. Returns lockfile path.
        Uses O_CREAT|O_EXCL for atomic creation (works on Windows + POSIX).
        """
        lockfile = path + ".lock"
        deadline = time.time() + LOCK_TIMEOUT

        while True:
            try:
                # Atomic create — fails if file exists
                fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                # Write PID for stale detection
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return lockfile
            except FileExistsError:
                # Lock exists. Only reclaim it if it's genuinely stale.
                try:
                    lock_age = time.time() - os.path.getmtime(lockfile)
                except OSError:
                    # Lock vanished between O_EXCL and getmtime — retry now.
                    continue

                if lock_age > LOCK_STALE_AGE:
                    # Reclaim the stale lock atomically: rename it to a
                    # per-process sentinel first, so at most one waiter wins
                    # the steal (losers get OSError and simply retry). This
                    # avoids two waiters both os.remove()-ing — and removing
                    # a lock a third writer just freshly acquired. The
                    # remaining mtime->rename window is microseconds against a
                    # 30s staleness threshold, so a live holder is never hit.
                    steal_path = f"{lockfile}.steal-{os.getpid()}"
                    try:
                        os.rename(lockfile, steal_path)
                        os.remove(steal_path)
                    except OSError:
                        pass  # someone else reclaimed/released it
                    continue

                if time.time() >= deadline:
                    # Timeout. Do NOT remove the lock — it may be held by a
                    # live writer mid-write; clobbering it would let a
                    # competing writer corrupt the file. Abort instead.
                    raise TimeoutError(f"Could not acquire lock: {lockfile}")

                time.sleep(LOCK_RETRY_INTERVAL)
            except OSError:
                # Parent dir might not exist yet
                parent = os.path.dirname(lockfile)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                if time.time() >= deadline:
                    raise TimeoutError(f"Could not acquire lock: {lockfile}")
                time.sleep(LOCK_RETRY_INTERVAL)

    def _release_lock(self, lockfile: str) -> None:
        """Release a lockfile."""
        try:
            os.remove(lockfile)
        except OSError:
            pass

    def _locked_read_modify_write(self, path: str, layer: str, modify_fn) -> None:
        """Lock -> reload from disk -> apply modification -> atomic write -> unlock."""
        lockfile = self._acquire_lock(path)
        try:
            existing = self._load_file(path, layer=layer)
            modified = modify_fn(existing)
            self._save_file(path, modified)
        finally:
            self._release_lock(lockfile)

    def _locked_save(self, path: str, memories: List[Memory]) -> None:
        """Lock -> atomic write -> unlock."""
        lockfile = self._acquire_lock(path)
        try:
            self._save_file(path, memories)
        finally:
            self._release_lock(lockfile)

    # ── Internal ────────────────────────────────────────────────

    def _load_file(self, path: str, layer: str = "project") -> List[Memory]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            # Parse entries individually — skip malformed, don't discard all
            memories = []
            for i, d in enumerate(data):
                try:
                    memories.append(Memory.from_dict(d))
                except (KeyError, TypeError, ValueError) as e:
                    log.warning("skipping malformed entry #%d in %s: %s", i, path, e)
                    continue

            # Ensure layer is set correctly
            for m in memories:
                m.layer = layer
            return memories

        except json.JSONDecodeError:
            # Corruption — quarantine the file, don't wipe it
            self._quarantine_file(path)
            return []
        except (OSError, IOError):
            return []

    def _quarantine_file(self, path: str) -> None:
        """Move a corrupted file to .corrupt-<timestamp> for recovery."""
        timestamp = int(time.time())
        quarantine_path = f"{path}.corrupt-{timestamp}"
        try:
            os.rename(path, quarantine_path)
            log.error("corrupted file quarantined: %s -> %s", path, quarantine_path)
        except OSError as e:
            log.error("could not quarantine corrupted file %s: %s", path, e)

    def _save_file(self, path: str, memories: List[Memory]) -> None:
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([m.to_dict() for m in memories], f, indent=2)
            # Durability: flush Python buffers + force data to disk before the
            # rename, so a power loss can't leave the renamed file pointing at
            # unwritten data. "Never forgets" depends on this.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        # fsync the directory so the rename itself survives a power loss (POSIX).
        self._fsync_dir(parent)

    @staticmethod
    def _fsync_dir(dirpath: str) -> None:
        """fsync a directory entry so a rename within it is durable.

        No-op on platforms that can't open a directory fd (e.g. Windows),
        where the file-level fsync above is the strongest guarantee available.
        """
        if not dirpath:
            return
        try:
            dir_fd = os.open(dirpath, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)
