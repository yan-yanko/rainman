"""
Example agent for the memory-lift harness.

Copy this and replace `solve()` with a call into your real coding agent. The
contract is the whole interface:

    solve(task, memory_context: str) -> bool   # True iff the task was resolved

`task` is an AgentTask (id, prompt, files, error). `memory_context` is the text
Rainman injected (the recalled memories), or "" on the memory-off arm. Your
agent should incorporate `memory_context` into its prompt/context and return
whether it resolved the task (e.g. the SWE-bench fail->pass tests now pass).

Run it:
    python eval/swebench/run_eval.py --tasks tasks.jsonl \
        --memories project_memories.jsonl \
        --agent eval.swebench.example_agent:EchoAgent
"""


class EchoAgent:
    """A trivial reference agent: 'resolves' a task iff its prompt's key term
    appears in the injected memory. Useful only to smoke-test the harness wiring
    — replace with a real agent."""

    def solve(self, task, memory_context: str) -> bool:
        # A real agent would run your model + tools here and return pass/fail.
        # This stub just checks whether memory mentioned the task's first word.
        key = task.prompt.split()[0].lower() if task.prompt else ""
        return bool(key) and key in (memory_context or "").lower()
