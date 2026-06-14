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
from rainman.core.text import (
    build_idf,
    tokenize,
    tokenize_query,
    tokenize_refs,
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

# Multiplier applied to a memory whose stored files / problem match the CURRENT
# task state (open file, recent error). Up to +TASK_AFFINITY_BOOST x at affinity
# 1.0 — surfaces the experience card for *this* file/error even when the
# free-text query doesn't lexically match it.
TASK_AFFINITY_BOOST = 0.8

# Auto-linking threshold (keyword overlap)
LINK_THRESHOLD = 0.25

# Max memories before oldest low-value entries are pruned
MAX_MEMORIES = 2000

# Consolidation (M5). A new note this similar to an existing one is treated as a
# re-observation and MERGED (reinforced) rather than stored as a duplicate.
DEDUP_THRESHOLD = 0.85
# A new memory carrying a supersession marker retires older memories it overlaps
# at least this much — the old knowledge is kept for the record but hidden.
SUPERSEDE_OVERLAP = 0.4
SUPERSESSION_MARKERS = (
    "no longer", "deprecated", "instead of", "migrated from", "migrated to",
    "replaced by", "replaced with", "superseded", "we now use", "switched from",
    "switched to", "moved away from", "rather than",
)

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
        return [
            m for m in mems
            if not m.metadata.get("quarantined")
            and not m.metadata.get("superseded_by")
        ]

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

        # M5: near-duplicate consolidation. A note this similar to an existing
        # one is a re-observation, not new knowledge — reinforce + merge metadata
        # instead of storing a duplicate. Experience cards (failure/solution with
        # a problem/fix payload) are intentional and never auto-merged.
        if category == "note" and "experience" not in metadata:
            dup = self._find_duplicate(content, layer)
            if dup is not None:
                dup.recall_count += 1
                dup.last_recalled = ts
                dup.timestamp = ts  # re-observed -> refresh recency
                if tags:
                    dup.tags = list(dict.fromkeys([*dup.tags, *tags]))[:MAX_TAGS]
                if file_refs:
                    dup.file_refs = list(dict.fromkeys([*dup.file_refs, *file_refs]))[:MAX_FILE_REFS]
                self.store.save_one(dup)
                self.audit.record(
                    "consolidate_merge", actor=author,
                    memory_ids=[dup.id], source=source,
                )
                return dup

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

        # Prune if over limit. When prune evicts entries the whole layer must be
        # rewritten: save_one() does a read-modify-write that re-merges the full
        # on-disk file and appends, so it would leave the evicted memories on
        # disk forever (the in-memory 2000-cap would silently diverge from an
        # ever-growing file). save_all() rewrites both layers from the pruned
        # set, so eviction actually reaches disk.
        pruned = False
        if len(self._memories) > MAX_MEMORIES:
            self._prune()
            pruned = True

        if pruned:
            self.store.save_all(self._memories)
        else:
            self.store.save_one(memory)
        self.audit.record(
            "store", actor=author, memory_ids=[memory.id],
            source=source, layer=layer, category=category,
        )

        # M5: supersession. New knowledge that explicitly contradicts/replaces
        # older knowledge ("we no longer use X", "migrated to Y") retires the
        # overlapping older memories — kept for the record (audit/history) but
        # hidden from recall via metadata.superseded_by.
        if any(mark in content.lower() for mark in SUPERSESSION_MARKERS):
            for old in self._find_superseded(content, layer, exclude_id=memory.id):
                old.metadata = {**old.metadata, "superseded_by": memory.id}
                self.store.save_one(old)
                self.audit.record(
                    "supersede", actor=author,
                    memory_ids=[old.id], superseded_by=memory.id,
                )

        return memory

    # ── Typed-causal experience cards (problem -> attempt -> outcome -> fix) ──
    #
    # The defensible signal for a coding agent isn't "file X was read"; it's
    # "this failed, then this fixed it." We capture failures as OPEN experience
    # cards and, when a later success touches the same files, pair them into a
    # resolved problem/fix card (ExpeL arXiv:2308.10144; Agent KB
    # arXiv:2507.06229). The typed payload lives in metadata["experience"] so no
    # schema/dataclass change is needed and old stores load unchanged.

    def record_failure(
        self,
        problem: str,
        command: Optional[str] = None,
        file_refs: Optional[List[str]] = None,
        source: str = "hook:post_tool_use",
        layer: str = "project",
    ) -> Optional[Memory]:
        """Store an OPEN failure experience card."""
        problem = (problem or "").strip()
        if not problem:
            return None
        experience = {
            "problem": problem[:MAX_CONTENT_LENGTH],
            "command": (command or "")[:500],
            "outcome": "open",
            "fix": None,
        }
        return self.add(
            content=f"Failure: {problem[:200]}",
            category="failure",
            file_refs=file_refs,
            source=source,
            layer=layer,
            metadata={"experience": experience},
        )

    def find_open_failure(
        self,
        file_refs: Optional[List[str]],
        within_seconds: float = 86400,
    ) -> Optional[Memory]:
        """Most-recent unresolved failure card whose files overlap ``file_refs``.

        Used to pair a passing run with the failure it resolved. Returns None if
        there's no open, file-overlapping failure inside the time window.
        """
        self._ensure_loaded()
        if not file_refs:
            return None
        ref_set = set(file_refs)
        now = time.time()
        candidates = [
            m for m in self._memories
            if m.category == "failure"
            and isinstance(m.metadata.get("experience"), dict)
            and m.metadata["experience"].get("outcome") == "open"
            and now - m.timestamp <= within_seconds
            and ref_set & set(m.file_refs)
        ]
        candidates.sort(key=lambda m: m.timestamp, reverse=True)
        return candidates[0] if candidates else None

    def resolve_failure(
        self,
        failure: Memory,
        fix: str,
        source: str = "hook:post_tool_use",
    ) -> Optional[Memory]:
        """Mark a failure card resolved and create a linked solution card.

        Returns the new solution Memory (the failure is updated in place and
        both directions of the link are persisted).
        """
        fix = (fix or "").strip()
        prior = failure.metadata.get("experience", {}) if failure.metadata else {}
        solution = self.add(
            content=f"Fix: {fix[:200]}",
            category="solution",
            file_refs=list(failure.file_refs),
            source=source,
            layer=failure.layer,
            metadata={"experience": {
                "problem": prior.get("problem"),
                "command": prior.get("command"),
                "outcome": "resolved",
                "fix": fix[:MAX_CONTENT_LENGTH],
                "resolved_failure": failure.id,
            }},
        )

        # Flip the failure card to resolved and cross-link the two.
        experience = {**prior, "outcome": "resolved",
                      "resolved_by": solution.id if solution else None,
                      "fix": fix[:MAX_CONTENT_LENGTH]}
        failure.metadata = {**failure.metadata, "experience": experience}
        if solution:
            if solution.id not in failure.linked_ids:
                failure.linked_ids.append(solution.id)
            if failure.id not in solution.linked_ids:
                solution.linked_ids.append(failure.id)
            self.store.save_one(solution)
        self.store.save_one(failure)
        return solution

    def recall(
        self,
        query: str,
        limit: int = 5,
        category: Optional[str] = None,
        min_trust=_UNSET,
        require_relevance: bool = True,
        context_files: Optional[List[str]] = None,
        error_signature: Optional[str] = None,
    ) -> List[RecallResult]:
        """
        Context-aware retrieval. Two-phase scoring with associative boost.
        Project memories get 1.2x boost over global.

        Task-state conditioning (M2): ``context_files`` (files currently being
        worked on) and ``error_signature`` (a recent error / stack trace) steer
        retrieval toward the memory for *this* situation. A memory referencing a
        current file, or whose experience-card ``problem`` matches the error, is
        boosted and is allowed past the relevance floor even with no lexical
        query overlap — so the fix for "this exact error in this exact file"
        surfaces regardless of how the query is phrased. The query may be empty
        when conditioning purely on task state.

        ``min_trust`` (one of trust.USER/HOOK/INGEST) gates out memories below
        that trust level entirely — a security control, distinct from the
        quality prior that only nudges ranking. When omitted, the org policy's
        ``recall_min_trust`` applies (default: no gate); pass None to force no
        gate regardless of policy.

        ``require_relevance`` (default True) applies a relevance FLOOR: when a
        query is given, a memory with no query signal at all (zero keyword AND
        zero associative score) is dropped rather than surfaced on recency
        alone. This stops an irrelevant-but-recent memory from being injected
        into the agent's context — confident noise is worse than nothing. Pass
        False to keep the old "always return the top-N by score" behavior.
        """
        self._ensure_loaded()
        query_words = query.split()

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

        # IDF over the candidate corpus — rare, meaningful terms outweigh common
        # ones (BM25's term-weighting principle). Built once per recall.
        idf = build_idf([
            set(tokenize(m.content))
            | set(tokenize_query(m.tags))
            | set(tokenize_refs(m.file_refs))
            for m in entries
        ])

        # Task state (M2): basenames of the current files + stemmed error terms.
        task_basenames = {
            f.replace("\\", "/").split("/")[-1].lower()
            for f in (context_files or [])
        }
        error_terms = set(tokenize(error_signature)) if error_signature else set()

        # Phase 1: Score without associative boost
        initial = []
        for entry in entries:
            scores = compute_score(entry, query_words, now=now, idf=idf)
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
                idf=idf,
            )

            total = scores["total"]

            # Project-layer boost
            if entry.layer == "project":
                total *= PROJECT_BOOST

            # Task-state affinity boost (current file / error signature).
            affinity = self._task_affinity(entry, task_basenames, error_terms, idf)
            if affinity > 0:
                total *= (1 + TASK_AFFINITY_BOOST * affinity)

            result = RecallResult(
                memory=entry,
                total_score=total,
                keyword_score=scores["keyword"],
                recency_score=scores["recency"],
                importance_score=scores["importance"],
                associative_score=scores["associative"],
                trust_prior=scores["trust_prior"],
                task_affinity=affinity,
            )
            results.append(result)

        # Relevance floor: drop memories with no relevance signal at all — no
        # keyword overlap, no associative link to a top result, AND no task-state
        # match. They would otherwise rank on recency/importance alone and inject
        # confident noise. The floor fires when there is something to be relevant
        # to: a real query OR task state. Skipped when the caller opts out, or
        # when neither is present (then recall degenerates to context-like).
        has_query = bool(tokenize_query(query_words))
        has_task = bool(task_basenames or error_terms)
        if require_relevance and (has_query or has_task):
            results = [
                r for r in results
                if r.keyword_score > 0.0
                or r.associative_score > 0.0
                or r.task_affinity > 0.0
            ]

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

    def _task_affinity(self, entry, task_basenames, error_terms, idf) -> float:
        """How well a memory matches the CURRENT task state, in [0, 1].

        Two signals: (1) the memory references a file currently in play; (2) the
        current error signature overlaps the memory's content or its
        experience-card ``problem`` (IDF-weighted, so a rare error token counts
        more than a common word). This is what lets the fix for *this* error in
        *this* file surface even when the free-text query doesn't match it.
        """
        score = 0.0

        if task_basenames and entry.file_refs:
            entry_basenames = {
                f.replace("\\", "/").split("/")[-1].lower() for f in entry.file_refs
            }
            if entry_basenames & task_basenames:
                score += 0.6

        if error_terms:
            entry_terms = set(tokenize(entry.content))
            exp = entry.metadata.get("experience") if entry.metadata else None
            if isinstance(exp, dict) and exp.get("problem"):
                entry_terms |= set(tokenize(exp["problem"]))
            matched = error_terms & entry_terms
            if matched:
                total_w = sum(idf.get(t, 1.0) for t in error_terms) or 1.0
                matched_w = sum(idf.get(t, 1.0) for t in matched)
                score += 0.6 * (matched_w / total_w)

        return min(1.0, score)

    def _find_duplicate(self, content: str, layer: str) -> Optional[Memory]:
        """Find an existing note that is a near-duplicate of ``content`` (same
        layer), by stemmed-token Jaccard >= DEDUP_THRESHOLD. Experience cards and
        superseded/quarantined memories are never merge targets."""
        new_tokens = set(tokenize(content))
        if len(new_tokens) < 3:
            return None  # too short to judge similarity reliably
        for m in self._memories:
            if m.layer != layer or m.category != "note":
                continue
            if m.metadata.get("experience") or m.metadata.get("superseded_by") \
                    or m.metadata.get("quarantined"):
                continue
            m_tokens = set(tokenize(m.content))
            if not m_tokens:
                continue
            jaccard = len(new_tokens & m_tokens) / len(new_tokens | m_tokens)
            if jaccard >= DEDUP_THRESHOLD:
                return m
        return None

    def _find_superseded(self, content: str, layer: str,
                         exclude_id: str) -> List[Memory]:
        """Older memories (same layer) that the new content retires: token
        overlap >= SUPERSEDE_OVERLAP, not already superseded, not the new one."""
        new_tokens = set(tokenize(content))
        if len(new_tokens) < 3:
            return []
        out = []
        for m in self._memories:
            if m.id == exclude_id or m.layer != layer:
                continue
            if m.metadata.get("superseded_by") or m.metadata.get("experience"):
                continue
            m_tokens = set(tokenize(m.content))
            if not m_tokens:
                continue
            overlap = len(new_tokens & m_tokens) / len(m_tokens)
            if overlap >= SUPERSEDE_OVERLAP:
                out.append(m)
        return out

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
