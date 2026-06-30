"""Tests for the retrieval-eval module + the memory-lift agent harness."""

import os

import pytest

from rainman.core.engine import RainmanEngine
from rainman.eval import (
    EvalCase,
    evaluate_retrieval,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from rainman.eval.agent_harness import AgentTask, KeywordMockAgent, compare_memory_on_off

# Reuse the gold corpus/queries from the IR gate.
from tests.test_retrieval_quality import GOLD_MEMORIES, GOLD_QUERIES


@pytest.mark.unit
class TestMetrics:

    def test_recall_at_k(self):
        assert recall_at_k(["a", "b", "c"], ["a", "x"], 3) == pytest.approx(0.5)
        assert recall_at_k(["a", "b"], ["a", "b"], 5) == pytest.approx(1.0)
        assert recall_at_k(["z"], ["a"], 3) == 0.0

    def test_precision_at_k(self):
        assert precision_at_k(["a", "b", "c"], ["a"], 3) == pytest.approx(1 / 3)
        assert precision_at_k([], ["a"], 0) == 0.0

    def test_reciprocal_rank(self):
        assert reciprocal_rank(["x", "a", "b"], ["a"]) == pytest.approx(0.5)
        assert reciprocal_rank(["a"], ["a"]) == 1.0
        assert reciprocal_rank(["x", "y"], ["a"]) == 0.0

    def test_mrr(self):
        cases = [(["a", "b"], ["a"]), (["x", "b"], ["b"])]
        assert mean_reciprocal_rank(cases) == pytest.approx((1.0 + 0.5) / 2)

    def test_ndcg(self):
        # one relevant item, retrieved at rank 1 -> perfect
        assert ndcg_at_k(["a", "b"], ["a"], 2) == pytest.approx(1.0)
        # at rank 2 -> 1/log2(3) normalized by ideal 1.0
        import math
        assert ndcg_at_k(["x", "a"], ["a"], 2) == pytest.approx(1 / math.log2(3))
        assert ndcg_at_k(["x"], [], 2) == 0.0


@pytest.fixture
def gold_engine(tmp_path):
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    labels_to_id = {}
    for label, (content, category) in GOLD_MEMORIES.items():
        m = e.add(content, category=category)
        labels_to_id[label] = m.id
    return e, labels_to_id


@pytest.mark.unit
class TestHarness:

    def test_evaluate_retrieval_on_gold_set(self, gold_engine):
        engine, labels_to_id = gold_engine
        cases = [
            EvalCase(query=q, relevant_ids=[labels_to_id[label]])
            for q, label in GOLD_QUERIES
        ]
        report = evaluate_retrieval(engine, cases, k=5)
        assert report.n_cases == len(GOLD_QUERIES)
        assert report.recall_at_k == pytest.approx(1.0)  # gate: all surfaced
        assert report.mrr >= 0.80
        assert "recall@5" in report.summary()


@pytest.mark.unit
class TestMemoryLiftHarness:

    def test_memory_on_beats_off_with_relevant_memory(self, tmp_path):
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        engine = RainmanEngine(project_dir=project, global_dir=global_dir)
        engine.store.init_project(project)
        engine.store.init_global()
        engine.add(
            "Fixed the auth 401: refresh-then-compare the token in middleware",
            category="solution", file_refs=["src/auth/middleware.py"],
        )
        tasks = [
            AgentTask(id="t1", prompt="users hit 401 after token refresh",
                      files=["src/auth/middleware.py"], error="HTTP 401"),
            AgentTask(id="t2", prompt="unrelated css grid flicker", files=["ui.css"]),
        ]
        agent = KeywordMockAgent(hints={"t1": "refresh-then-compare"})
        report = compare_memory_on_off(engine, tasks, agent)

        assert report["off_resolved"] == 0          # no context -> mock fails
        assert report["on_resolved"] == 1            # memory surfaced the fix
        assert report["delta_pp"] > 0
        assert report["newly_resolved"] == ["t1"]

    def test_empty_task_list(self, tmp_path):
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        engine = RainmanEngine(project_dir=project, global_dir=global_dir)
        engine.store.init_project(project)
        engine.store.init_global()
        report = compare_memory_on_off(engine, [], KeywordMockAgent({}))
        assert report["n"] == 0
        assert report["delta_pp"] == 0.0


@pytest.mark.unit
class TestSequentialBench:
    """Guards for eval/local_demo/sequential_memory_bench.py — the
    non-tautological, sequential, same-repo memory benchmark."""

    def test_chain_is_memory_dependent(self):
        """The point of the benchmark: a memoryless agent fails the dependent
        tasks (it can't know the project's earned conventions), while an agent
        with retrieval resolves them. If this stops holding, the chain no longer
        tests memory."""
        from eval.local_demo.sequential_memory_bench import _mock_run, score, CHAIN
        result = score(_mock_run())
        n = result["n"]
        # Only the establishing task (no prior dep) is solvable with no memory.
        assert result["resolved"]["none"] == 1
        # Retrieval (Rainman) resolves the whole chain.
        assert result["resolved"]["rainman"] == n
        assert result["lift_vs_none_pp"] > 0
        # Every non-establishing task requires earned knowledge.
        assert sum(1 for s in CHAIN if s["requires"]) == n - 1

    def test_no_self_leak_is_non_tautological(self):
        """The core honesty invariant: a task's OWN earned knowledge must never
        be in the context it is judged on — only EARLIER tasks' knowledge. The
        required token may legitimately recur in a later task's context, but it
        must be absent from the establishing task's own context for every arm."""
        from eval.local_demo.sequential_memory_bench import build_cases, CHAIN, ARMS, _present
        cases = {c["id"]: c for c in build_cases()}
        for step in CHAIN:
            for cat, content, _refs in step["establishes"]:
                ctx_blob = " ".join(cases[step["id"]]["contexts"][a] for a in ARMS)
                # The distinctive phrase this task establishes must not be visible
                # to itself (it is added to the store only AFTER the task runs).
                assert content not in ctx_blob, f"{step['id']} leaked its own answer"

    def test_rainman_context_is_tighter_than_grep(self):
        """Even when both surface the earned fact, Rainman's relevance floor
        injects fewer items than a top-k grep that pads with weak matches."""
        from eval.local_demo.sequential_memory_bench import context_stats
        stats = context_stats()
        assert stats["rainman"]["avg_items"] <= stats["file"]["avg_items"]

    def test_rainman_holds_at_scale_where_grep_degrades(self):
        """The scale separation: at a tiny store, file-memory grep ties Rainman
        (both surface the earned card). As realistic domain-overlapping noise
        piles up between tasks, the earned card ages out of grep's top-k (its
        match-count+recency ranking can't recover it), while Rainman keeps it via
        IDF + importance + task-affinity. If this stops holding, the scale claim
        in the README is wrong."""
        from eval.local_demo.sequential_memory_bench import _mock_run, score
        small = score(_mock_run(0))
        scaled = score(_mock_run(50))
        # Tiny store: grep ties Rainman.
        assert small["resolved"]["file"] == small["resolved"]["rainman"]
        # At scale: Rainman holds the whole chain; grep falls behind it.
        assert scaled["resolved"]["rainman"] == small["n"]
        assert scaled["resolved"]["rainman"] > scaled["resolved"]["file"]
