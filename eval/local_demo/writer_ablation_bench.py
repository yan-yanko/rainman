#!/usr/bin/env python3
"""
Who should WRITE memory? — hooks vs the model vs both (writer ablation)
=======================================================================

Every other bench in this folder holds the WRITE side fixed (hand-authored
cards, or record_failure() called directly) and varies retrieval. This one
holds RETRIEVAL fixed and varies only who decides what gets stored.

Motivation: Anthropic's "components of agent memory" research (Nov 2026)
reports that for strong models, letting the model judge salience beat fixed
rules set in advance. One fixed rule, "record only failures", cut the memory
gain by 0.234 for Opus 5. Rainman's auto-learn hooks are a fixed rule set:
keyword salience lists, the first line of a Read, Bash outcome parsing, and
trigger-phrase transcript mining. So: do the hooks add anything over the model
calling `remember` itself?

Setup: eight realistic Claude-Code-style SESSIONS in one fictional repo
("Tidewater"). Each has a user ask, tool events (Read/Edit/Write/Bash + output)
and the assistant's closing message. Six carry a durable, unguessable fact a
LATER task needs. Two are exploration/volatile-state sessions that carry
nothing durable (branch name, coverage %), which is what the article calls
"screen-visible" state and should NOT be stored.

Four arms. The same sessions feed every arm:

  none   no memory.
  hooks  every tool event replayed through the REAL auto-learn pipeline
         (integration.core.learn_from_tool, the PostToolUse path), then the
         assistant text through capture_learnings (the SessionEnd path).
         Zero LLM.
  model  a real model reads each session's transcript and decides what to
         store with Rainman's own `remember` MCP tool contract (same
         description the server ships). It is told what memory is for, not
         how to use it. Recorded in writer_model_memories.json. Memories are
         stored through engine.add(source="mcp"), the same call the MCP
         server makes.
  both   hooks + model into one store.

Then six PROBE tasks (phrased differently, different files) each need one fact.
Retrieval is identical for every arm: build_memory_context() = engine.recall()
top-k with task-state conditioning.

Metrics per arm:
  covered   the fact exists ANYWHERE in the store (write-side ceiling)
  surfaced  the fact is in the injected top-k context (what the agent sees)
  store     number of memories / characters written
  volatile  memories that hold screen-visible state that goes stale
  precision fraction of injected lines that carry the probe's fact

    python eval/local_demo/writer_ablation_bench.py              # score all arms
    python eval/local_demo/writer_ablation_bench.py --scale      # bury the store in noise
    python eval/local_demo/writer_ablation_bench.py --contexts   # what each arm injected
    python eval/local_demo/writer_ablation_bench.py --stores     # what each arm WROTE
    python eval/local_demo/writer_ablation_bench.py --writer-prompts DIR
        # write one prompt per session to DIR, to feed fresh model instances.
        # Collect their JSON into a file shaped like writer_model_memories.json.
    python eval/local_demo/writer_ablation_bench.py --model-memories PATH
    python eval/local_demo/writer_ablation_bench.py --json out.json

SCOPE HONESTY: what this does NOT show
  * Small and synthetic: 8 sessions, 6 probes, one fictional repo. The facts'
    placement (test output, deep in a file, prose, the user's own message)
    decides the result. That is why results are reported PER FACT TYPE, not
    as one headline number. Read the table, not the total.
  * The model writer sees the WHOLE session at the end (hindsight), like the
    SessionEnd hook does. A model writing in-flow is distracted by the task
    (the article's point), and may write less.
  * Writing costs the model tokens and attention. This measures memory
    quality only, not that cost. The hooks' zero-token, zero-distraction
    write is a real advantage this bench does not price.
  * Grading is token presence in the injected context, not task success. It
    measures "did the agent get to see the fact", the precondition.
  * One model run per session. No variance estimate.
"""

import argparse
import json
import os
import re
import tempfile

from rainman.core.engine import RainmanEngine
from rainman.eval.agent_harness import AgentTask, build_memory_context
from rainman.integration import core

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_MEMORIES = os.path.join(HERE, "writer_model_memories.json")
ROOT = "/work/tidewater"  # fictional project root; paths are made relative to it


def _p(rel: str) -> str:
    return f"{ROOT}/{rel}"


# --- the sessions ------------------------------------------------------------
# Written the way real sessions look: the fact sits wherever it naturally would
# (a test failure, a docstring, the assistant's prose, the user's own message).
# `fact_type` labels WHERE the durable fact lives, for the per-type breakdown.
SESSIONS = [
    {
        "id": "s1",
        "fact_type": "failure->fix (test run)",
        "user": "Creating invoices in parallel sometimes 500s. Can you look?",
        "events": [
            ("Bash", {"command": "pytest tests/test_invoices.py -x"},
             "FAILED tests/test_invoices.py::test_parallel_create - sqlalchemy.exc."
             "IntegrityError: duplicate key value violates unique constraint "
             "\"invoices_number_key\"\n1 failed, 14 passed in 3.2s"),
            ("Read", {"file_path": _p("src/invoices/numbering.py")},
             '"""Invoice number allocation."""\nfrom sqlalchemy import func\n\n'
             "def allocate_number(session):\n"
             "    last = session.query(func.max(Invoice.number)).scalar() or 0\n"
             "    return last + 1\n"),
            ("Edit", {"file_path": _p("src/invoices/numbering.py"),
                      "old_string": "last = session.query(func.max(Invoice.number)).scalar() or 0\n"
                                    "    return last + 1",
                      "new_string": "return next_invoice_seq(session)  # Postgres sequence, race-free"},
             "ok"),
            ("Bash", {"command": "pytest tests/test_invoices.py"}, "15 passed in 3.4s"),
        ],
        "assistant": "Root cause: allocate_number() read MAX(number)+1, which races when two "
                     "requests create invoices at the same time. I replaced it with "
                     "next_invoice_seq(session), which draws from the Postgres sequence "
                     "invoice_number_seq, so allocation is atomic. All 15 invoice tests pass.",
        "volatile": [],
    },
    {
        "id": "s2",
        "fact_type": "failure->fix (test run)",
        "user": "CI is red again on webhooks. Flaky?",
        "events": [
            ("Bash", {"command": "pytest tests/test_webhooks.py"},
             "FAILED tests/test_webhooks.py::test_retry_delivery - TimeoutError: delivery "
             "did not complete within 10s\n1 failed, 8 passed in 12.1s"),
            ("Read", {"file_path": _p("pytest.ini")},
             "[pytest]\nmarkers =\n    slow: slow tests\nenv =\n    TIDE_WEBHOOK_TIMEOUT=10\n"),
            ("Edit", {"file_path": _p("pytest.ini"),
                      "old_string": "TIDE_WEBHOOK_TIMEOUT=10",
                      "new_string": "TIDE_WEBHOOK_TIMEOUT=45"}, "ok"),
            ("Bash", {"command": "pytest tests/test_webhooks.py"}, "9 passed in 41.0s"),
        ],
        "assistant": "test_retry_delivery runs three backoff rounds, which takes about 35s on "
                     "CI runners, but pytest.ini capped webhook delivery at 10s via "
                     "TIDE_WEBHOOK_TIMEOUT. I raised it to 45. Not a product bug, just the "
                     "test environment's ceiling.",
        "volatile": [],
    },
    {
        "id": "s3",
        "fact_type": "convention read in code",
        "user": "Add a helper that formats an invoice total for the email template.",
        "events": [
            ("Read", {"file_path": _p("src/money.py")},
             '"""Money helpers.\n\nAll monetary amounts in Tidewater are integers in MILLICENTS\n'
             '(1/1000 of a cent) so FX conversion never rounds. Never divide by 100.\n"""\n\n'
             "def to_display(amount: int, currency: str) -> str:\n"
             '    return f"{amount / 100_000:.2f} {currency}"\n'),
            ("Write", {"file_path": _p("src/emails/format.py"),
                       "content": "from src.money import to_display\n\n"
                                  "def format_invoice_total(inv):\n"
                                  "    return to_display(inv.total, inv.currency)\n"}, "ok"),
            ("Bash", {"command": "pytest tests/test_emails.py"}, "4 passed in 0.6s"),
        ],
        "assistant": "Added format_invoice_total() in src/emails/format.py. It delegates to "
                     "money.to_display() because amounts are stored as millicents, so "
                     "dividing by 100 would be off by 1000x. Tests pass.",
        "volatile": [],
    },
    {
        "id": "s4",
        "fact_type": "decision in prose (trigger phrase)",
        "user": "PDF rendering is blocking the API workers. What are our options?",
        "events": [
            ("Read", {"file_path": _p("src/pdf/render.py")},
             "from tidewater.tasks import task\n\n@task()\ndef render_invoice_pdf(invoice_id):\n"
             "    doc = build_document(invoice_id)\n    return doc.to_pdf()\n"),
            ("Read", {"file_path": _p("docs/arch/queues.md")},
             "# Queues\n\nTidewater runs two queues: `default` (Celery, shared) and "
             "`bulkhead` (isolated workers, concurrency 2).\n"),
            ("Edit", {"file_path": _p("src/pdf/render.py"),
                      "old_string": "@task()", "new_string": "@task(queue=\"bulkhead\")"}, "ok"),
        ],
        "assistant": "Two options: render on the default Celery queue (simple, but a burst of "
                     "PDFs starves invoice emails) or on the isolated bulkhead queue. We "
                     "decided to go with the bulkhead queue for all PDF rendering: "
                     "render_invoice_pdf is now dispatched with queue='bulkhead'.",
        "volatile": [],
    },
    {
        "id": "s5",
        "fact_type": "decision in prose (no trigger phrase)",
        "user": "Customers want a CSV export of transactions. Where should this live?",
        "events": [
            ("Read", {"file_path": _p("src/exports/README.md")},
             "Exports\n=======\n\nAll file exports are produced by the quarry service "
             "(services/quarry). The public API only enqueues an export job and returns a "
             "job id. It never builds files inline, because large tenants time out.\n"),
            ("Edit", {"file_path": _p("src/api/transactions.py"),
                      "old_string": "# exports",
                      "new_string": "@router.post('/transactions/export')\n"
                                    "def export(req):\n"
                                    "    return {'job_id': quarry.enqueue_export('transactions', req.tenant)}"},
             "ok"),
        ],
        "assistant": "Added POST /transactions/export, which enqueues a quarry job and returns "
                     "its id, matching how the other exports work. I didn't build the CSV in "
                     "the request handler, since large tenants would time out.",
        "volatile": [],
    },
    {
        "id": "s6",
        "fact_type": "user instruction",
        "user": "Rename the cust_id column to customer_id everywhere. Oh, and don't touch "
                "anything under src/legacy/. Finance owns it; ask in #fin-platform if "
                "something there needs changing.",
        "events": [
            ("Bash", {"command": "grep -rn cust_id src/"},
             "src/models/customer.py:12: cust_id = Column(Integer)\n"
             "src/legacy/billing_v1.py:40: row.cust_id\n"),
            ("Edit", {"file_path": _p("src/models/customer.py"),
                      "old_string": "cust_id = Column(Integer)",
                      "new_string": "customer_id = Column(Integer)"}, "ok"),
            ("Write", {"file_path": _p("migrations/0042_rename_customer_id.py"),
                       "content": "op.alter_column('customers', 'cust_id', new_column_name='customer_id')\n"},
             "ok"),
            ("Bash", {"command": "pytest"}, "212 passed, 3 skipped in 48.2s"),
        ],
        "assistant": "Renamed cust_id to customer_id across src/ (11 files) and added "
                     "migration 0042. Left src/legacy/billing_v1.py unchanged as asked; it "
                     "still reads cust_id through its own mapper. Full suite passes.",
        "volatile": [],
    },
    {
        "id": "s7",
        "fact_type": "(no durable fact) volatile state",
        "user": "What's our coverage right now, and which branch am I on?",
        "events": [
            ("Bash", {"command": "git branch --show-current"}, "feature/inv-212"),
            ("Bash", {"command": "pytest --cov=src -q"},
             "212 passed, 3 skipped\nTOTAL    4410    712    84%"),
            ("Read", {"file_path": _p("README.md")},
             "# Tidewater\n\nBilling platform for multi-currency invoicing.\n\n"
             "See docs/ for architecture notes and CONTRIBUTING.md for setup.\n"),
        ],
        "assistant": "You're on feature/inv-212 and line coverage is 84% (712 of 4410 lines "
                     "uncovered).",
        "volatile": ["feature/inv-212", "84%"],
    },
    {
        "id": "s8",
        "fact_type": "(no durable fact) code exploration",
        "user": "Walk me through how login works.",
        "events": [
            ("Read", {"file_path": _p("src/auth/session.py")},
             '"""Session handling."""\nSESSION_TTL = 3600\n\ndef create_session(user):\n'
             "    return redis.setex(f\"sess:{user.id}\", SESSION_TTL, user.token)\n"),
            ("Read", {"file_path": _p("src/auth/oauth.py")},
             '"""OAuth login via the tidewater-idp provider."""\nPROVIDER = "tidewater-idp"\n'
             "def callback(req):\n    return exchange_code(req.args['code'])\n"),
            ("Read", {"file_path": _p("config/settings.py")},
             "DEBUG = False\nREDIS_URL = env('REDIS_URL')\nIDP_ISSUER = env('IDP_ISSUER')\n"),
        ],
        "assistant": "Login is OAuth against tidewater-idp: oauth.callback exchanges the code, "
                     "then session.create_session stores a session in Redis for an hour "
                     "(SESSION_TTL=3600).",
        "volatile": [],
    },
]

# --- the probes (later tasks; different wording, different files) ------------
# `requires` = list of alternative spellings; ANY one present (word-boundary,
# case-insensitive) counts. Alternatives keep grading fair to a model that
# paraphrases ("1/1000 of a cent" vs "millicents").
PROBES = [
    {"id": "p1", "from": "s1",
     "prompt": "I'm adding a bulk invoice import that creates hundreds of invoices "
               "concurrently. How should invoice numbers be assigned?",
     "files": ["src/invoices/bulk_import.py"], "error": "",
     "requires": ["next_invoice_seq", "invoice_number_seq"]},
    {"id": "p2", "from": "s2",
     "prompt": "test_retry_delivery is timing out locally after 10 seconds. Known issue?",
     "files": ["tests/test_webhooks.py"],
     "error": "TimeoutError: delivery did not complete within 10s",
     "requires": ["TIDE_WEBHOOK_TIMEOUT"]},
    {"id": "p3", "from": "s3",
     "prompt": "Show refund amounts in the customer portal as dollars. How do I convert "
               "the stored amount?",
     "files": ["src/portal/refunds.py"], "error": "",
     "requires": ["millicents", "millicent", "1/1000"]},
    {"id": "p4", "from": "s4",
     "prompt": "Generating the monthly statement PDF is slow. Which queue should the "
               "Celery task run on?",
     "files": ["src/statements/pdf.py"], "error": "",
     "requires": ["bulkhead"]},
    {"id": "p5", "from": "s5",
     "prompt": "Add an endpoint that exports a customer's invoices as a ZIP of PDFs.",
     "files": ["src/api/invoices.py"], "error": "",
     "requires": ["quarry"]},
    {"id": "p6", "from": "s6",
     "prompt": "src/legacy/billing_v1.py still says cust_id. Let's rename it there too.",
     "files": ["src/legacy/billing_v1.py"], "error": "",
     "requires": ["fin-platform", "finance"]},
]

ARMS = ("none", "hooks", "model", "both")


# --- transcript rendering (what the model writer sees) ------------------------
def render_transcript(session) -> str:
    out = [f"USER: {session['user']}", ""]
    for tool, inp, output in session["events"]:
        args = json.dumps({k: (v.replace(ROOT + "/", "") if isinstance(v, str) else v)
                           for k, v in inp.items()})
        out.append(f"TOOL CALL {tool} {args}")
        out.append("TOOL RESULT:")
        out.append(output.rstrip())
        out.append("")
    out.append(f"ASSISTANT: {session['assistant']}")
    return "\n".join(out)


REMEMBER_TOOL = {
    "name": "remember",
    "description": (
        "Store a new learning in project memory. Use when you discover something "
        "important: a fix that worked, a decision made, a pattern found, a failure "
        "to avoid. This persists across sessions."
    ),
    "input": {
        "content": "string, the knowledge to remember",
        "category": "one of pattern | solution | failure | decision | convention | note",
        "tags": "optional list of strings",
        "file_refs": "optional list of related file paths",
    },
}


def writer_prompt(session) -> str:
    """The model-arm prompt. It says what memory is FOR, not what to store
    (the article's recommendation). It never mentions the probes."""
    return (
        "You are a coding agent working in the Tidewater repository. The session "
        "below has just finished. This is your last turn before the session ends.\n\n"
        "Future sessions in this repo start with no memory of this one, except what "
        "you store with the `remember` tool. A store that holds the right things helps "
        "later sessions; a store full of noise hurts them.\n\n"
        f"Tool:\n{json.dumps(REMEMBER_TOOL, indent=2)}\n\n"
        "Decide what, if anything, to remember. Reply with ONLY a JSON array of "
        "`remember` argument objects (an empty array is a valid answer). No prose.\n\n"
        "=== SESSION TRANSCRIPT ===\n"
        f"{render_transcript(session)}\n"
        "=== END ==="
    )


# --- building each arm's store ------------------------------------------------
def _fresh_engine():
    tmp = tempfile.mkdtemp(prefix="writer_ablation_")
    engine = RainmanEngine(project_dir=os.path.join(tmp, "p"),
                           global_dir=os.path.join(tmp, "g"))
    engine.store.init_project(os.path.join(tmp, "p"))
    engine.store.init_global()
    return engine


def replay_hooks(engine, session) -> None:
    """Run one session through the real auto-learn pipeline, exactly as the
    Claude Code adapters call it: PostToolUse per event, then SessionEnd."""
    for tool, inp, output in session["events"]:
        core.learn_from_tool(engine, tool, dict(inp), output, ROOT)
    core.capture_learnings(engine, session["assistant"], ROOT)


def apply_model_memories(engine, calls) -> None:
    """Store model-chosen memories the way the MCP `remember` tool does."""
    for c in calls:
        content = (c.get("content") or "").strip()
        if not content:
            continue
        engine.add(content=content, category=c.get("category", "note"),
                   tags=c.get("tags") or [], file_refs=c.get("file_refs") or [],
                   source="mcp", layer="project")


def load_model_memories(path=MODEL_MEMORIES):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("sessions", data)


def _seed_noise(engine, n: int) -> None:
    """Months of unrelated, domain-overlapping memories (payments vocabulary,
    no answer tokens), seeded identically into every arm BEFORE the sessions.
    Reuses the sequential bench's generator so the noise is not tuned here."""
    if n <= 0:
        return
    try:
        from eval.local_demo.sequential_memory_bench import _noise
    except ImportError:  # run as a script: this folder is on sys.path instead
        from sequential_memory_bench import _noise
    for cat, content, refs in _noise(n):
        engine.add(content, category=cat, file_refs=refs, source="mcp", layer="project")


def build_store(arm: str, model_memories=None, noise: int = 0):
    engine = _fresh_engine()
    if arm == "none":
        return engine
    _seed_noise(engine, noise)
    for s in SESSIONS:
        if arm in ("hooks", "both"):
            replay_hooks(engine, s)
        if arm in ("model", "both"):
            if model_memories is None:
                raise SystemExit("model arm needs a recorded run (--model-memories)")
            apply_model_memories(engine, model_memories.get(s["id"], []))
    return engine


# --- grading ------------------------------------------------------------------
def _present(token: str, text: str) -> bool:
    text, tok = (text or "").lower(), token.lower()
    for m in re.finditer(re.escape(tok), text):
        before = text[m.start() - 1] if m.start() > 0 else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            return True
    return False


def has_fact(text: str, requires) -> bool:
    return any(_present(t, text) for t in requires)


def _all_memories(engine):
    return list(engine.store.load_all())


def evaluate(arm: str, model_memories=None, k: int = 5, noise: int = 0) -> dict:
    engine = build_store(arm, model_memories, noise)
    mems = _all_memories(engine)
    store_text = "\n".join(m.content for m in mems)
    volatile_tokens = [t for s in SESSIONS for t in s["volatile"]]
    volatile = sum(1 for m in mems if any(_present(t, m.content) for t in volatile_tokens))

    rows = []
    hit_lines = total_lines = 0
    for p in PROBES:
        task = AgentTask(id=p["id"], prompt=p["prompt"], files=p["files"], error=p["error"])
        ctx = build_memory_context(engine, task, k=k) if arm != "none" else ""
        lines = [ln for ln in ctx.splitlines() if ln.startswith("[")]
        good = sum(1 for ln in lines if has_fact(ln, p["requires"]))
        hit_lines += good
        total_lines += len(lines)
        src = next(s for s in SESSIONS if s["id"] == p["from"])
        rows.append({
            "probe": p["id"], "fact_type": src["fact_type"],
            "covered": has_fact(store_text, p["requires"]),
            "surfaced": has_fact(ctx, p["requires"]),
            "injected": len(lines), "context": ctx,
        })
    return {
        "arm": arm,
        "store_size": len(mems),
        "store_chars": len(store_text),
        "volatile": volatile,
        "covered": sum(r["covered"] for r in rows),
        "surfaced": sum(r["surfaced"] for r in rows),
        "precision": round(hit_lines / total_lines, 2) if total_lines else None,
        "rows": rows,
        "memories": [{"category": m.category, "source": m.source, "content": m.content}
                     for m in mems],
    }


def run_all(model_memories=None, k: int = 5, noise: int = 0):
    arms = [a for a in ARMS if model_memories is not None or a in ("none", "hooks")]
    return {a: evaluate(a, model_memories, k, noise) for a in arms}


def print_scale(model_memories, k: int = 5, levels=(0, 50, 200, 500)) -> None:
    """Does each arm's fact still surface once the store is big enough that
    top-k can no longer just inject everything?"""
    arms = [a for a in ARMS if a != "none" and (model_memories is not None or a == "hooks")]
    n = len(PROBES)
    print(f"surfaced@{k} as unrelated memories pile up (noise seeded into every arm)\n")
    print(f"{'noise':>6}" + "".join(f"{a:>9}" for a in arms))
    print("-" * (6 + 9 * len(arms)))
    for lvl in levels:
        res = {a: evaluate(a, model_memories, k, lvl) for a in arms}
        print(f"{lvl:>6}" + "".join(f"{str(res[a]['surfaced']) + '/' + str(n):>9}" for a in arms))


# --- output -------------------------------------------------------------------
def _mark(row):
    if row["surfaced"]:
        return "HIT"
    return "stored" if row["covered"] else "-"


def print_table(results) -> None:
    arms = list(results)
    n = len(PROBES)
    print("Per probe: HIT = fact injected in top-k; stored = in the store but not "
          "surfaced; - = never written\n")
    print(f"{'probe':6}{'fact lives in':38}" + "".join(f"{a:>8}" for a in arms))
    print("-" * (44 + 8 * len(arms)))
    for i, p in enumerate(PROBES):
        ft = results[arms[0]]["rows"][i]["fact_type"]
        print(f"{p['id']:6}{ft:38}" + "".join(f"{_mark(results[a]['rows'][i]):>8}" for a in arms))
    print()
    print(f"{'':44}" + "".join(f"{a:>8}" for a in arms))
    for label, key in (("covered (written at all)", "covered"),
                       ("surfaced (injected top-k)", "surfaced")):
        print(f"{label:44}" + "".join(f"{str(results[a][key]) + '/' + str(n):>8}" for a in arms))
    print(f"{'store size (memories)':44}" + "".join(f"{results[a]['store_size']:>8}" for a in arms))
    print(f"{'store chars':44}" + "".join(f"{results[a]['store_chars']:>8}" for a in arms))
    print(f"{'volatile/stale memories':44}" + "".join(f"{results[a]['volatile']:>8}" for a in arms))
    print(f"{'injected-line precision':44}"
          + "".join(f"{('-' if results[a]['precision'] is None else results[a]['precision']):>8}"
                    for a in arms))
    if "model" not in results:
        print("\n(model/both arms need a recorded run: --model-memories PATH)")


def print_stores(results) -> None:
    for arm, r in results.items():
        if arm == "none":
            continue
        print(f"=== {arm}: {r['store_size']} memories ===")
        for m in r["memories"]:
            print(f"  [{m['category']:10}] ({m['source']}) {m['content'][:150]}")
        print()


def print_contexts(results) -> None:
    for i, p in enumerate(PROBES):
        print(f"### {p['id']} needs one of {p['requires']}\n    {p['prompt']}")
        for arm, r in results.items():
            if arm == "none":
                continue
            ctx = r["rows"][i]["context"] or "(nothing)"
            print(f"  [{arm}]\n    " + ctx.replace("\n", "\n    "))
        print()


def write_prompts(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for s in SESSIONS:
        path = os.path.join(out_dir, f"{s['id']}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(writer_prompt(s))
        print(path)


def main(argv=None):
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()

    ap = argparse.ArgumentParser(description="Writer ablation: hooks vs model vs both")
    ap.add_argument("--model-memories", default=MODEL_MEMORIES,
                    help="Recorded model-writer run (JSON). Default: the bundled run.")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--noise", type=int, default=0,
                    help="Unrelated memories seeded into every arm first (default 0).")
    ap.add_argument("--scale", action="store_true", help="Sweep noise 0/50/200/500.")
    ap.add_argument("--contexts", action="store_true", help="Print each arm's injected context.")
    ap.add_argument("--stores", action="store_true", help="Print what each arm wrote.")
    ap.add_argument("--writer-prompts", metavar="DIR", help="Write model-writer prompts to DIR.")
    ap.add_argument("--json", metavar="PATH", help="Write the full results as JSON.")
    a = ap.parse_args(argv)

    if a.writer_prompts:
        write_prompts(a.writer_prompts)
        return 0

    if a.scale:
        print_scale(load_model_memories(a.model_memories), k=a.k)
        return 0

    results = run_all(load_model_memories(a.model_memories), k=a.k, noise=a.noise)
    if a.stores:
        print_stores(results)
    elif a.contexts:
        print_contexts(results)
    else:
        print_table(results)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
