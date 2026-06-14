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
