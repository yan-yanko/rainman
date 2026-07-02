"""
Rainman Data Models
====================

Memory entries and recall results for project knowledge.
Adapted from CogniTrait — stripped of persona/Big Five dependencies.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Memory categories for project knowledge
CATEGORIES = {
    "pattern",      # recurring code/architecture pattern
    "solution",     # fix for a specific problem
    "failure",      # what went wrong and why
    "decision",     # architectural/design decision and rationale
    "convention",   # project convention or rule
    "note",         # general knowledge
}

# Sentiment labels (adapted from CogniTrait emotions)
SENTIMENTS = {
    "positive", "negative", "neutral",
    "anxious", "frustrated", "excited",
}


@dataclass
class Memory:
    """A single project knowledge entry."""
    id: str
    content: str
    timestamp: float
    importance: float                        # 0-1, auto-calculated
    category: str = "note"                   # pattern|solution|failure|decision|convention|note
    sentiment: str = "neutral"               # positive|negative|neutral|anxious|frustrated|excited
    linked_ids: List[str] = field(default_factory=list)   # associative graph edges
    recall_count: int = 0                    # rehearsal (ACT-R)
    last_recalled: Optional[float] = None
    tags: List[str] = field(default_factory=list)         # user-defined tags
    source: str = ""                         # "git:abc123"|"cli"|"mcp"|"hook:post_tool_use"
    file_refs: List[str] = field(default_factory=list)    # files this memory relates to
    layer: str = "project"                   # "project" | "global"
    author: str = ""                         # actor who created it (provenance)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def trust(self) -> str:
        """Trust level derived from source: user | hook | ingest."""
        from rainman.core.trust import trust_level
        return trust_level(self.source)

    @property
    def memory_type(self) -> str:
        """Cognitive memory type — DERIVED, no stored field, no migration.

        Mirrors the declarative-memory taxonomy (Squire; Tulving):
          episodic   a context-tagged SPECIFIC EVENT (time + place): a
                     typed-causal experience card, or a failure/solution anchored
                     to file_refs — "this happened, here."
          procedural a reusable rule / how-to: a convention or pattern.
          semantic   a context-free FACT: a decision, note, or a lesson with no
                     place anchor — and any consolidated GENERALIZATION (an
                     abstraction extracted across many events is semantic).
        """
        md = self.metadata if isinstance(self.metadata, dict) else {}
        if md.get("consolidated"):
            return "semantic"
        if "experience" in md or (self.category in ("failure", "solution") and self.file_refs):
            return "episodic"
        if self.category in ("convention", "pattern"):
            return "procedural"
        return "semantic"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "timestamp": self.timestamp,
            "importance": self.importance,
            "category": self.category,
            "sentiment": self.sentiment,
            "linked_ids": self.linked_ids,
            "recall_count": self.recall_count,
            "last_recalled": self.last_recalled,
            "tags": self.tags,
            "source": self.source,
            "file_refs": self.file_refs,
            "layer": self.layer,
            "author": self.author,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Memory":
        return cls(
            id=d["id"],
            content=d["content"],
            timestamp=d["timestamp"],
            importance=d["importance"],
            category=d.get("category", "note"),
            sentiment=d.get("sentiment", "neutral"),
            linked_ids=d.get("linked_ids", []),
            recall_count=d.get("recall_count", 0),
            last_recalled=d.get("last_recalled"),
            tags=d.get("tags", []),
            source=d.get("source", ""),
            file_refs=d.get("file_refs", []),
            layer=d.get("layer", "project"),
            author=d.get("author", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class RecallResult:
    """A single recall result with score breakdown."""
    memory: Memory
    total_score: float
    keyword_score: float = 0.0
    recency_score: float = 0.0
    importance_score: float = 0.0
    associative_score: float = 0.0
    trust_prior: float = 1.0   # quality-prior multiplier applied to total (tiebreaker)
    task_affinity: float = 0.0  # task-state match (current file / error signature), 0-1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory": self.memory.to_dict(),
            "total_score": round(self.total_score, 4),
            "keyword_score": round(self.keyword_score, 4),
            "recency_score": round(self.recency_score, 4),
            "importance_score": round(self.importance_score, 4),
            "associative_score": round(self.associative_score, 4),
            "trust": self.memory.trust,
            "memory_type": self.memory.memory_type,
            "trust_prior": round(self.trust_prior, 4),
            "task_affinity": round(self.task_affinity, 4),
        }
