"""
Storage backend selection
==========================

The engine talks to storage through a small, stable interface. Two
implementations satisfy it:

  * ``MemoryStore``  (rainman.core.store)        — JSON files. Default.
                                                   git-committable, diff-friendly.
  * ``SqliteStore``  (rainman.core.sqlite_store) — WAL SQLite. No 2000-cap,
                                                   real concurrency, indexes.

Selection is the ``storage_backend`` policy key (``json`` | ``sqlite``,
default ``json``). Switch an existing store with ``rainman migrate``.

KNOWN LIMITATION (Phase 2a): the selected backend applies to BOTH the project
and the shared global layer. Because policy can be set per-project, two
projects sharing the same global store could in principle disagree on the
global backend. To stay consistent, set ``storage_backend`` at the user/global
(``~/.rainman/config.json``) or org-policy level rather than per-project, and
migrate once. Multi-consumer consistency of the shared store is properly solved
by the sync server (Phase 2b).
"""

from typing import Dict, List, Optional, Protocol, runtime_checkable

from rainman.core.models import Memory


@runtime_checkable
class StorageBackend(Protocol):
    """The persistence contract the engine depends on."""

    def load_all(self) -> List[Memory]: ...
    def save_all(self, memories: List[Memory]) -> None: ...
    def save_one(self, memory: Memory) -> None: ...
    def save_layers(self, memories: List[Memory], layers: set) -> None: ...
    def update_rehearsal_stats(self, updates: Dict[str, dict], layer: str) -> None: ...
    def get_stats(self) -> Dict: ...
    def schema_version(self, layer: str = "project") -> Optional[int]: ...
    def audit_path(self) -> str: ...
    def init_project(self, project_dir: str) -> str: ...
    def init_global(self) -> str: ...
    def global_dir(self) -> str: ...


def make_store(project_dir: Optional[str], global_dir: Optional[str],
               backend: str = "json") -> StorageBackend:
    """Construct the configured storage backend."""
    if backend == "sqlite":
        from rainman.core.sqlite_store import SqliteStore
        return SqliteStore(project_dir=project_dir, global_dir=global_dir)
    from rainman.core.store import MemoryStore
    return MemoryStore(project_dir=project_dir, global_dir=global_dir)
