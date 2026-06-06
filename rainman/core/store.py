"""
Layered JSON Persistence
=========================

Two-layer storage: global (~/.rainman/) + project (.rainman/).
Project memories get a 1.2x boost on recall.

JSON files, human-readable, git-committable.
No database. No server.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from rainman.core.models import Memory


# Default directories
GLOBAL_DIR = os.path.join(str(Path.home()), ".rainman")
PROJECT_DIR_NAME = ".rainman"


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
        self._save_file(global_path, global_memories)

        # Save project
        if self._project_dir:
            project_path = os.path.join(self._project_dir, "memories.json")
            self._save_file(project_path, project_memories)

    def save_one(self, memory: Memory) -> None:
        """Append or update a single memory in the appropriate layer."""
        if memory.layer == "global":
            path = os.path.join(self._global_dir, "memories.json")
        elif self._project_dir:
            path = os.path.join(self._project_dir, "memories.json")
        else:
            # No project dir, fall back to global
            memory.layer = "global"
            path = os.path.join(self._global_dir, "memories.json")

        existing = self._load_file(path, layer=memory.layer)
        # Update in-place if memory already exists, else append
        updated = False
        for i, m in enumerate(existing):
            if m.id == memory.id:
                existing[i] = memory
                updated = True
                break
        if not updated:
            existing.append(memory)
        self._save_file(path, existing)

    def save_layers(self, memories: List[Memory], layers: set) -> None:
        """Save only the specified layers. Avoids full rewrite on recall."""
        if "global" in layers:
            global_memories = [m for m in memories if m.layer == "global"]
            global_path = os.path.join(self._global_dir, "memories.json")
            self._save_file(global_path, global_memories)

        if "project" in layers and self._project_dir:
            project_memories = [m for m in memories if m.layer == "project"]
            project_path = os.path.join(self._project_dir, "memories.json")
            self._save_file(project_path, project_memories)

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

    # ── Internal ────────────────────────────────────────────────

    def _load_file(self, path: str, layer: str = "project") -> List[Memory]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            memories = [Memory.from_dict(d) for d in data]
            # Ensure layer is set correctly
            for m in memories:
                m.layer = layer
            return memories
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def _save_file(self, path: str, memories: List[Memory]) -> None:
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([m.to_dict() for m in memories], f, indent=2)
            os.replace(tmp, path)
        except OSError:
            # If atomic replace fails, try direct write as fallback
            try:
                os.remove(tmp)
            except OSError:
                pass
            with open(path, "w", encoding="utf-8") as f:
                json.dump([m.to_dict() for m in memories], f, indent=2)
