"""Guards for eval/local_demo/writer_ablation_bench.py: who should WRITE
memory (auto-learn hooks vs the model's own `remember` calls vs both)."""

import pytest


@pytest.mark.unit
class TestWriterAblationBench:

    def test_no_probe_leaks_into_writer_prompts(self):
        """The model writer must never see the later tasks it is judged on."""
        from eval.local_demo.writer_ablation_bench import (
            PROBES,
            SESSIONS,
            writer_prompt,
        )
        for s in SESSIONS:
            prompt = writer_prompt(s)
            for p in PROBES:
                assert p["prompt"] not in prompt

    def test_every_probe_fact_exists_in_its_source_session(self):
        """Each probe's fact must actually be learnable from its session,
        otherwise a miss measures the scenario, not the writer."""
        from eval.local_demo.writer_ablation_bench import (
            PROBES,
            SESSIONS,
            has_fact,
            render_transcript,
        )
        by_id = {s["id"]: s for s in SESSIONS}
        for p in PROBES:
            assert has_fact(render_transcript(by_id[p["from"]]), p["requires"]), p["id"]

    def test_none_arm_is_empty(self):
        from eval.local_demo.writer_ablation_bench import evaluate
        r = evaluate("none")
        assert r["store_size"] == 0 and r["surfaced"] == 0

    def test_hooks_arm_runs_the_real_pipeline(self):
        """The hooks arm goes through integration.core, so it stores the
        typed-causal failure cards that pipeline produces."""
        from eval.local_demo.writer_ablation_bench import evaluate
        r = evaluate("hooks")
        sources = {m["source"] for m in r["memories"]}
        assert "hook:post_tool_use:Bash" in sources
        assert any(m["category"] == "failure" for m in r["memories"])
        assert r["surfaced"] <= r["covered"]

    def test_model_arm_stores_through_remember_contract(self):
        from eval.local_demo.writer_ablation_bench import evaluate
        calls = {"s1": [{"content": "Invoice numbers come from next_invoice_seq(session).",
                         "category": "convention",
                         "file_refs": ["src/invoices/numbering.py"]}]}
        r = evaluate("model", calls)
        assert r["store_size"] == 1
        assert r["memories"][0]["source"] == "mcp"
        p1 = next(row for row in r["rows"] if row["probe"] == "p1")
        assert p1["covered"] and p1["surfaced"]

    def test_bundled_model_run_loads(self):
        from eval.local_demo.writer_ablation_bench import SESSIONS, load_model_memories
        data = load_model_memories()
        assert data is not None
        assert set(data) == {s["id"] for s in SESSIONS}
