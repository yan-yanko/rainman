"""
Rainman Engine
===============

Core memory operations: add, recall, link, forget.
Adapted from CogniTrait — stripped of Big Five personality modulation.

Two-phase retrieval:
1. Score all entries without associative boost -> find top-K
2. Re-score with associative boost using top-K as anchors

All operations are local, zero-LLM, zero-cost.
"""

import time
import uuid
from typing import Dict, List, Optional, Any

from rainman.core.models import Memory, RecallResult, CATEGORIES
from rainman.core.sentiment import classify_sentiment
from rainman.core.identity import current_actor
from rainman.core.audit import AuditLogger, audit_enabled
from rainman.core.config import load_policy
from rainman.core import trust
from rainman.core.scoring import (
    compute_score,
    build_reverse_link_index,
    CATEGORY_IMPORTANCE,
    IMPORTANCE_KEYWORDS,
)
from rainman.core.store import GLOBAL_DIR
from rainman.core.storage import make_store


# ── Input limits ──────────────────────────────────────────────
MAX_CONTENT_LENGTH = 5000
MIN_CONTENT_LENGTH = 5
MAX_TAG_LENGTH = 50
MAX_TAGS = 20
MAX_FILE_REFS = 20
MAX_FILE_REF_LENGTH = 500


# Project-layer boost on recall (local knowledge is more relevant)
PROJECT_BOOST = 1.2

# Auto-linking threshold (keyword overlap)
LINK_THRESHOLD = 0.25

# Max memories before oldest low-value entries are pruned
MAX_MEMORIES = 2000

# Sentinel: caller didn't pass min_trust, so fall back to org policy.
_UNSET = object()


class RainmanEngine:
    """
    Context-aware project memory.

    Add knowledge, recall it by context, auto-link related entries.
    Layered storage: global + project.
    """

    def __init__(
        self,
        project_dir: Optional[str] = None,
        global_dir: Optional[str] = None,
    ):
        # Policy first — it decides which storage backend to use. Policy load
        # only needs the directory paths, not a constructed store.
        resolved_global = global_dir or GLOBAL_DIR
        self.policy = load_policy(project_dir=project_dir, global_dir=resolved_global)
        self.store = make_store(
            project_dir=project_dir,
            global_dir=global_dir,
            backend=self.policy.get("storage_backend"),
        )
        self._memories: List[Memory] = []
        self._loaded = False
        audit_on = bool(self.policy.get("audit")) or audit_enabled()
        self.audit = AuditLogger(self.store.audit_path(), enabled=audit_on)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            # Keep the in-memory set COMPLETE (both layers). save_all() persists
            # whatever is in self._memories across layers, so filtering here
            # would let a later save (forget / retention) wipe the dropped
            # layer. Visibility filtering happens at read time in _visible().
            self._memories = self.store.load_all()
            self._loaded = True
            self._apply_retention()

    def _visible(self) -> List[Memory]:
        """Memories eligible to surface: minus quarantined, minus the global
        layer when org policy disables it. Never used for persistence."""
        mems = self._memories
        if self.policy.get("disable_global_layer"):
            mems = [m for m in mems if m.layer != "global"]
        return [m for m in mems if not m.metadata.get("quarantined")]

    def _apply_retention(self) -> None:
        """Delete memories older than the org retention TTL (compliance).

        Operates on the complete loaded set and persists the removal. Applies
        across layers — when an org enforces retention it means "we do not keep
        data older than N days," period.
        """
        days = self.policy.get("retention_days")
        if not days or days <= 0:
            return
        cutoff = time.time() - days * 86400
        expired = [m for m in self._memories if m.timestamp < cutoff]
        if not expired:
            return
        self._memories = [m for m in self._memories if m.timestamp >= cutoff]
        self.store.save_all(self._memories)
        self.audit.record(
            "retention_prune", actor="system",
            memory_ids=[m.id for m in expired], retention_days=days,
        )

    # ── Public API ──────────────────────────────────────────────

    def add(
        self,
        content: str,
        category: str = "note",
        sentiment: Optional[str] = None,
        importance: Optional[float] = None,
        tags: Optional[List[str]] = None,
        file_refs: Optional[List[str]] = None,
        source: str = "cli",
        layer: str = "project",
        metadata: Optional[Dict[str, Any]] = None,
        author: Optional[str] = None,
    ) -> Optional[Memory]:
        """Add a memory with auto-sentiment and auto-linking.

        Returns None if content is too short after stripping.
        """
        self._ensure_loaded()

        # ── Input validation ──
        content = content.strip()
        if len(content) < MIN_CONTENT_LENGTH:
            return None
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH]

        if category not in CATEGORIES:
            category = "note"

        # Org policy: forbidden categories are rejected outright.
        if category in self.policy.get("category_denylist"):
            return None

        if layer not in ("project", "global"):
            layer = "project"

        # Org policy: when the global layer is disabled, global writes fall
        # back to the project layer rather than silently vanishing.
        if layer == "global" and self.policy.get("disable_global_layer"):
            layer = "project"

        # Sanitize tags
        if tags:
            tags = [t.strip()[:MAX_TAG_LENGTH] for t in tags[:MAX_TAGS] if t.strip()]
        # Sanitize file_refs
        if file_refs:
            file_refs = [f.strip()[:MAX_FILE_REF_LENGTH] for f in file_refs[:MAX_FILE_REFS] if f.strip()]

        ts = time.time()

        if sentiment is None:
            sentiment = classify_sentiment(content)

        if importance is None:
            importance = self._calc_importance(content, category)

        if author is None:
            author = current_actor()

        # Org policy: hold third-party (ingest) memories in quarantine — stored
        # for the record but not recallable until reviewed (review queue: Ph2).
        if metadata is None:
            metadata = {}
        if self.policy.get("quarantine_ingest") and trust.trust_level(source) == trust.INGEST:
            metadata = {**metadata, "quarantined": True}

        memory = Memory(
            id=f"rm_{int(ts * 1000)}_{uuid.uuid4().hex[:6]}",
            content=content,
            timestamp=ts,
            importance=importance,
            category=category,
            sentiment=sentiment,
            linked_ids=self._find_related(content),
            tags=tags or [],
            source=source,
            file_refs=file_refs or [],
            layer=layer,
            author=author,
            metadata=metadata or {},
        )

        self._memories.append(memory)

        # Prune if over limit
        if len(self._memories) > MAX_MEMORIES:
            self._prune()

        self.store.save_one(memory)
        self.audit.record(
            "store", actor=author, memory_ids=[memory.id],
            source=source, layer=layer, category=category,
        )
        return memory

    def recall(
        self,
        query: str,
        limit: int = 5,
        category: Optional[str] = None,
        min_trust=_UNSET,
    ) -> List[RecallResult]:
        """
        Context-aware retrieval. Two-phase scoring with associative boost.
        Project memories get 1.2x boost over global.

        ``min_trust`` (one of trust.USER/HOOK/INGEST) gates out memories below
        that trust level entirely — a security control, distinct from the
        quality prior that only nudges ranking. When omitted, the org policy's
        ``recall_min_trust`` applies (default: no gate); pass None to force no
        gate regardless of policy.
        """
        self._ensure_loaded()
        query_words = query.lower().split()

        if not self._memories:
            return []

        if min_trust is _UNSET:
            min_trust = self.policy.get("recall_min_trust")

        entries = self._visible()
        if category:
            entries = [m for m in entries if m.category == category]
        if min_trust is not None:
            floor = trust.RANK[min_trust]
            entries = [m for m in entries if trust.trust_rank(m.source) >= floor]

        if not entries:
            return []

        now = time.time()

        # Trust ranks for the associative restriction (boost can't flow from a
        # higher-trust anchor down to a lower-trust entry).
        trust_index = {m.id: trust.trust_rank(m.source) for m in entries}

        # Phase 1: Score without associative boost
        initial = []
        for entry in entries:
            scores = compute_score(entry, query_words, now=now)
            initial.append((entry, scores))

        initial.sort(key=lambda x: x[1]["total"], reverse=True)
        top_ids = [e.id for e, _ in initial[:limit]]

        # Phase 2: Re-score with associative boost
        reverse_index = build_reverse_link_index(entries)
        results = []
        for entry in entries:
            scores = compute_score(
                entry, query_words,
                top_ids=top_ids,
                all_entries=entries,
                reverse_index=reverse_index,
                now=now,
                trust_index=trust_index,
            )

            total = scores["total"]

            # Project-layer boost
            if entry.layer == "project":
                total *= PROJECT_BOOST

            result = RecallResult(
                memory=entry,
                total_score=total,
                keyword_score=scores["keyword"],
                recency_score=scores["recency"],
                importance_score=scores["importance"],
                associative_score=scores["associative"],
                trust_prior=scores["trust_prior"],
            )
            results.append(result)

        results.sort(key=lambda r: r.total_score, reverse=True)

        # Update access stats on returned entries
        top_results = results[:limit]
        updates_by_layer: Dict[str, Dict[str, dict]] = {}
        for r in top_results:
            r.memory.recall_count += 1
            r.memory.last_recalled = now
            layer = r.memory.layer
            if layer not in updates_by_layer:
                updates_by_layer[layer] = {}
            updates_by_layer[layer][r.memory.id] = {
                "recall_count": r.memory.recall_count,
                "last_recalled": r.memory.last_recalled,
            }

        # Persist only the stats that changed (locked per-entry update)
        for layer, updates in updates_by_layer.items():
            self.store.update_rehearsal_stats(updates, layer)

        if self.audit.enabled:
            self.audit.record(
                "recall", actor=current_actor(),
                memory_ids=[r.memory.id for r in top_results],
                query=query[:200],
            )

        return top_results

    def context(self, limit: int = 10, min_trust: Optional[str] = None) -> List[RecallResult]:
        """
        Get current working context: recent + high-importance memories.
        No query needed — returns a blend of what's fresh and what matters.

        ``min_trust`` gates out memories below that trust level. Unsolicited
        context injection (SessionStart) is the most dangerous poisoning path —
        the user sees no query and makes no choice — so callers there pass a
        stricter floor than explicit recall.
        """
        self._ensure_loaded()
        if not self._memories:
            return []

        entries = self._visible()
        if min_trust is not None:
            floor = trust.RANK[min_trust]
            entries = [m for m in entries if trust.trust_rank(m.source) >= floor]

        now = time.time()
        scored = []

        for entry in entries:
            # Blend recency (60%) and importance (40%) for context
            days = max(0, (now - entry.timestamp) / 86400)
            recency = 1 / (1 + days ** 0.5)
            imp = CATEGORY_IMPORTANCE.get(entry.category, 0.4)

            total = 0.6 * recency + 0.4 * imp
            if entry.layer == "project":
                total *= PROJECT_BOOST

            scored.append(RecallResult(
                memory=entry,
                total_score=total,
                recency_score=recency,
                importance_score=imp,
            ))

        scored.sort(key=lambda r: r.total_score, reverse=True)
        return scored[:limit]

    def links(self, ref: str) -> List[Memory]:
        """Find all memories linked to a file or concept."""
        self._ensure_loaded()
        ref_lower = ref.lower()
        results = []

        for m in self._visible():
            # Check file_refs
            for fref in m.file_refs:
                if ref_lower in fref.lower():
                    results.append(m)
                    break
            else:
                # Check content
                if ref_lower in m.content.lower():
                    results.append(m)
                # Check tags
                elif any(ref_lower in t.lower() for t in m.tags):
                    results.append(m)

        return results

    def link(self, id_a: str, id_b: str) -> bool:
        """Manually link two memories."""
        self._ensure_loaded()
        a = self._find_by_id(id_a)
        b = self._find_by_id(id_b)
        if not a or not b:
            return False

        if id_b not in a.linked_ids:
            a.linked_ids.append(id_b)
        if id_a not in b.linked_ids:
            b.linked_ids.append(id_a)

        self.store.save_all(self._memories)
        return True

    def refresh(self, memory_id: str) -> bool:
        """Refresh a memory's timestamp without creating a duplicate.

        Used by hooks when dedup fires — keeps the memory fresh instead
        of silently dropping the update.
        """
        self._ensure_loaded()
        m = self._find_by_id(memory_id)
        if not m:
            return False
        m.timestamp = time.time()
        m.recall_count += 1
        m.last_recalled = m.timestamp
        self.store.save_one(m)
        return True

    def forget(self, memory_id: str) -> bool:
        """Remove a specific memory."""
        self._ensure_loaded()
        before = len(self._memories)
        self._memories = [m for m in self._memories if m.id != memory_id]
        if len(self._memories) < before:
            self.store.save_all(self._memories)
            self.audit.record("forget", actor=current_actor(), memory_ids=[memory_id])
            return True
        return False

    # ── Review queue (quarantined memories) ─────────────────────

    def list_quarantined(self) -> List[Memory]:
        """Memories held in quarantine awaiting review (see quarantine_ingest)."""
        self._ensure_loaded()
        return [m for m in self._memories if m.metadata.get("quarantined")]

    def review_approve(self, memory_id: str) -> bool:
        """Clear a memory's quarantine flag so it becomes recallable."""
        self._ensure_loaded()
        m = self._find_by_id(memory_id)
        if not m or not m.metadata.get("quarantined"):
            return False
        m.metadata.pop("quarantined", None)
        self.store.save_one(m)
        self.audit.record(
            "review_approve", actor=current_actor(),
            memory_ids=[memory_id], source=m.source,
        )
        return True

    def review_reject(self, memory_id: str) -> bool:
        """Permanently drop a quarantined memory (rejected at review)."""
        self._ensure_loaded()
        m = self._find_by_id(memory_id)
        if not m or not m.metadata.get("quarantined"):
            return False
        layer = m.layer
        self._memories = [x for x in self._memories if x.id != memory_id]
        self.store.save_layers(self._memories, {layer})
        self.audit.record(
            "review_reject", actor=current_actor(),
            memory_ids=[memory_id], source=m.source,
        )
        return True

    def get_stats(self) -> Dict:
        """Return memory statistics."""
        return self.store.get_stats()

    def get_all(self) -> List[Memory]:
        """Return all memories."""
        self._ensure_loaded()
        return list(self._memories)

    # ── Internal ────────────────────────────────────────────────

    def _calc_importance(self, content: str, category: str) -> float:
        """Calculate importance score from category + keywords."""
        base = CATEGORY_IMPORTANCE.get(category, 0.40)
        words = set(content.lower().split())
        if words & IMPORTANCE_KEYWORDS:
            base = min(1.0, base + 0.15)
        return base

    def _find_related(self, content: str, max_links: int = 3) -> List[str]:
        """Find related memories by keyword overlap."""
        if not self._memories:
            return []

        content_words = set(content.lower().split())
        if len(content_words) < 2:
            return []

        scored = []
        # Only check recent 100 for speed
        for entry in self._memories[-100:]:
            entry_words = set(entry.content.lower().split())
            if not entry_words:
                continue
            overlap = len(content_words & entry_words) / max(
                len(content_words), len(entry_words)
            )
            if overlap >= LINK_THRESHOLD:
                scored.append((entry.id, overlap))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [eid for eid, _ in scored[:max_links]]

    def _find_by_id(self, memory_id: str) -> Optional[Memory]:
        for m in self._memories:
            if m.id == memory_id:
                return m
        return None

    def _prune(self) -> None:
        """Remove oldest low-value memories when over MAX_MEMORIES."""
        # Sort by importance * recency, remove bottom 10%
        now = time.time()
        scored = []
        for m in self._memories:
            days = max(0, (now - m.timestamp) / 86400)
            recency = 1 / (1 + days ** 0.5)
            score = m.importance * 0.5 + recency * 0.3 + (min(m.recall_count, 10) * 0.1) * 0.2
            scored.append((m, score))

        scored.sort(key=lambda x: x[1])
        n_remove = max(0, len(self._memories) - MAX_MEMORIES)
        if n_remove == 0:
            return
        remove_ids = {m.id for m, _ in scored[:n_remove]}
        self._memories = [m for m in self._memories if m.id not in remove_ids]
