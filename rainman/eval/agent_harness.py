"""
Memory-on vs memory-off agent harness
======================================

The plumbing for the headline proof: does injecting Rainman's memory raise a
coding agent's task-success rate? This module is dataset- and agent-agnostic —
you bring a real agent (an ``AgentProtocol``) and a list of ``AgentTask`` (e.g.
SWE-bench Verified instances) and it runs each task twice (with memory injected
and without) and reports the delta.

It deliberately ships NO results and NO bundled model — running it against a
real benchmark with a real agent is what produces a number. ``eval/swebench/``
at the repo root is the SWE-bench entrypoint that uses this.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Protocol, Sequence


@dataclass
class AgentTask:
    """One benchmark task. ``id`` must be unique; ``files``/``error`` feed
    task-state-conditioned recall (M2)."""
    id: str
    prompt: str
    files: List[str] = field(default_factory=list)
    error: str = ""


class AgentProtocol(Protocol):
    """A coding agent under test. Returns True iff it resolved the task.

    ``memory_context`` is the (possibly empty) text Rainman injected — the same
    string in both arms is "" for the memory-off run.
    """

    def solve(self, task: AgentTask, memory_context: str) -> bool:
        ...


def build_memory_context(engine, task: AgentTask, k: int = 5,
                         semantic_provider=None) -> str:
    """Recall the memories Rainman would inject for this task, as text."""
    results = engine.recall(
        task.prompt,
        limit=k,
        context_files=task.files or None,
        error_signature=task.error or None,
        semantic_provider=semantic_provider,
    )
    if not results:
        return ""
    lines = [f"[{r.memory.category}] {r.memory.content}" for r in results]
    return "Relevant project memory:\n" + "\n".join(lines)


def run_suite(engine, tasks: Sequence[AgentTask], agent: AgentProtocol,
              memory_on: bool, k: int = 5, semantic_provider=None) -> Dict[str, bool]:
    """Run every task once; return {task_id: resolved}."""
    outcomes: Dict[str, bool] = {}
    for task in tasks:
        context = build_memory_context(engine, task, k=k,
                                       semantic_provider=semantic_provider) if memory_on else ""
        outcomes[task.id] = bool(agent.solve(task, context))
    return outcomes


def compare_memory_on_off(engine, tasks: Sequence[AgentTask], agent: AgentProtocol,
                          k: int = 5, semantic_provider=None) -> Dict[str, object]:
    """Run the suite memory-off then memory-on; return the resolution delta.

    ``delta_pp`` is the headline artifact: percentage-point lift in resolved
    tasks from injecting memory.
    """
    if not tasks:
        return {"n": 0, "off_resolved": 0, "on_resolved": 0,
                "off_rate": 0.0, "on_rate": 0.0, "delta_pp": 0.0, "newly_resolved": []}

    off = run_suite(engine, tasks, agent, memory_on=False, k=k,
                    semantic_provider=semantic_provider)
    on = run_suite(engine, tasks, agent, memory_on=True, k=k,
                   semantic_provider=semantic_provider)

    n = len(tasks)
    off_resolved = sum(1 for v in off.values() if v)
    on_resolved = sum(1 for v in on.values() if v)
    newly = sorted(tid for tid in on if on[tid] and not off.get(tid))
    return {
        "n": n,
        "off_resolved": off_resolved,
        "on_resolved": on_resolved,
        "off_rate": off_resolved / n,
        "on_rate": on_resolved / n,
        "delta_pp": (on_resolved - off_resolved) / n * 100.0,
        "newly_resolved": newly,
    }


class KeywordMockAgent:
    """A deterministic stand-in agent for DRY RUNS and tests ONLY.

    It "resolves" a task iff the injected memory context contains the task's
    hint keyword — so it resolves more with memory than without. This proves the
    on/off plumbing end-to-end; it is NOT a benchmark result and must never be
    reported as one.
    """

    def __init__(self, hints: Dict[str, str]):
        self._hints = hints  # task_id -> keyword that must appear in memory

    def solve(self, task: AgentTask, memory_context: str) -> bool:
        hint = self._hints.get(task.id)
        if hint is None:
            return False
        return hint.lower() in (memory_context or "").lower()
