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

from rainman.core.models import Memory


# Default directories
GLOBAL_DIR = os.path.join(str(Path.home()), ".rainman")
PROJECT_DIR_NAME = ".rainman"

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
                json.dump({"version": "0.1.0", "project": ""}, f, indent=2)

        self._project_dir = target
        return target

    def init_global(self) -> str:
        """Initialize ~/.rainman/ global store."""
        os.makedirs(self._global_dir, exist_ok=True)

        memories_path = os.path.join(self._global_dir, "memories.json")
        if not os.path.exists(memories_path):
            self._save_file(memories_path, [])

        config_path = os.path.join(self._global_dir, "config.json")
        if not os.path.exists(config_path):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"version": "0.1.0"}, f, indent=2)

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
                # Check if lock is stale
                try:
                    lock_age = time.time() - os.path.getmtime(lockfile)
                    if lock_age > LOCK_STALE_AGE:
                        # Stale lock — remove and retry
                        try:
                            os.remove(lockfile)
                        except OSError:
                            pass
                        continue
                except OSError:
                    pass

                if time.time() >= deadline:
                    # Timeout — force remove stale lock
                    try:
                        os.remove(lockfile)
                    except OSError:
                        pass
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
                    import sys
                    print(
                        f"[rainman] skipping malformed entry #{i} in {path}: {e}",
                        file=sys.stderr,
                    )
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
        import sys
        timestamp = int(time.time())
        quarantine_path = f"{path}.corrupt-{timestamp}"
        try:
            os.rename(path, quarantine_path)
            print(
                f"[rainman] corrupted file quarantined: {path} -> {quarantine_path}",
                file=sys.stderr,
            )
        except OSError as e:
            print(
                f"[rainman] could not quarantine corrupted file {path}: {e}",
                file=sys.stderr,
            )

    def _save_file(self, path: str, memories: List[Memory]) -> None:
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([m.to_dict() for m in memories], f, indent=2)
        os.replace(tmp, path)
