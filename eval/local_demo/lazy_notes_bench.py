#!/usr/bin/env python3
"""
Rainman vs the notes a REAL human keeps — the lazy-notes bench
==============================================================

The scaled live-agent run (`sequential_memory_bench.py`) ended in an honest
tie — but its file-memory arm assumed a DILIGENT human: every learning,
including every routine failure->fix pair, written to the notes file. Real
humans don't do that. They write up the big outage and the architecture
decision; they do not transcribe the Tuesday-afternoon flaky-test fix. Rainman's
auto-learn hooks capture exactly that undramatic tail with zero discipline.

This bench measures what that coverage asymmetry is worth, DETERMINISTICALLY —
no LLM, no agent, fully reproducible:

  * A simulated work history of incidents, each = (error signature, file, fix).
    Four are "notable" (outage/decision-grade — a human writes those up); the
    rest are routine debugging (a human usually doesn't).
  * The NOTES arm gets a curated markdown file holding the notable write-ups
    plus a --diligence fraction of the routine fixes. Retrieval is the same
    fair grep model as `file_memory_vs_rainman.py` (whole-word match over the
    error's distinctive terms, recency tiebreak) over a SMALL, NOISE-FREE file
    — the easiest possible grep target.
  * The RAINMAN arm gets every incident through the hook's real API
    (`record_failure` -> `resolve_failure`), the notable decisions as
    session_end-style cards, PLUS --noise auto-learn filler cards — because
    auto-capture also stores junk, its store is BIGGER and DIRTIER than the
    notes file. Retrieval is error-conditioned recall, the way a hook would
    call it when the error recurs: `recall("", context_files=[...],
    error_signature=...)` — no hand-written query at all.
  * Each incident's error then RECURS (slightly varied text, as real
    recurrences are). Hit = the incident's fix surfaced in the top-k.
  * CONTROL errors that were never seen: both arms must surface nothing.

End-to-end hit rate decomposes as coverage x retrieval-given-coverage. The
sweep over --diligence separates the two: grep's retrieval-given-coverage can
be excellent while its ceiling is whatever the human bothered to write down.

    python eval/local_demo/lazy_notes_bench.py                  # sweep 0/33/67/100% diligence
    python eval/local_demo/lazy_notes_bench.py --noise 200      # bury Rainman's store deeper
    python eval/local_demo/lazy_notes_bench.py --contexts       # show what each side surfaced
    python eval/local_demo/lazy_notes_bench.py --json out.json  # machine-readable artifact

SCOPE HONESTY — what this does NOT show:
  * Rainman's 100% incident coverage is CONDITIONAL on the hook firing and the
    salience gate passing. That pairing mechanism is unit-tested
    (test_experience.py) but real transcripts can still miss captures; this
    bench measures retrieval given capture, and capture given the mechanism.
  * The notes arm is mechanical grep. A human (or LLM) re-READING a small notes
    file is a stronger fuzzy matcher — but it still cannot read a note that was
    never written, which is the variable under test.
  * Synthetic incidents, small-N. This is a mechanism measurement, not a
    SWE-bench task-success number (see ../swebench/).
"""

import argparse
import json
import os
import re
import tempfile

from rainman.core.engine import RainmanEngine


# --- the simulated work history ---------------------------------------------
# Each incident: id, notable?, file, error (first sighting), recur (the later,
# slightly-varied sighting used as the query), fix, and the note a human writes
# IF they record it (prose, the way people actually write notes — describing
# the problem and fix, not pasting the stack trace).
INCIDENTS = [
    # -- notable: outage/decision-grade; a real human writes these up ---------
    dict(id="pool", notable=True, file="app/db.py",
         error="sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out",
         recur="sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out (worker 3)",
         fix="Raise pool_size to 20 and enable pool_pre_ping so stale connections get recycled",
         note="Postmortem: the API brownout was SQLAlchemy connection pool exhaustion under load. Raised pool_size to 20 and enabled pool_pre_ping."),
    dict(id="jwt", notable=True, file="app/auth.py",
         error="jwt.exceptions.ExpiredSignatureError: Signature has expired (exp claim seconds in the past)",
         recur="jwt.exceptions.ExpiredSignatureError: Signature has expired on refresh for mobile session",
         fix="Pass leeway=30 to jwt.decode — mobile client clocks drift",
         note="Decision: JWT validation allows 30 seconds of clock-skew leeway because mobile device clocks drift and tokens expired early."),
    dict(id="webhook", notable=True, file="app/webhooks.py",
         error="WebhookSignatureError: X-Hub-Signature-256 mismatch on partner callback payload",
         recur="WebhookSignatureError: X-Hub-Signature-256 mismatch from partner sandbox",
         fix="Compute the HMAC over the raw request body bytes before any JSON parsing",
         note="Webhook HMAC signatures must be computed over the raw body bytes; re-serializing the JSON reorders keys and breaks verification."),
    dict(id="migrate", notable=True, file="migrations/0042_add_index.py",
         error="psycopg2.errors.LockNotAvailable: canceling statement due to lock timeout during ALTER TABLE users",
         recur="psycopg2.errors.LockNotAvailable: canceling statement due to lock timeout (ALTER TABLE users ADD COLUMN)",
         fix="Create the index CONCURRENTLY with lock_timeout=5s and run it off-peak",
         note="Convention: never run a plain CREATE INDEX / ALTER on the users table in prod — use CONCURRENTLY with a 5s lock_timeout, off-peak."),
    # -- routine: everyday debugging; a real human usually does NOT write these
    dict(id="dst", notable=False, file="tests/test_billing.py",
         error="AssertionError in test_billing_rollover: assert rollover_at == datetime(2026, 3, 29, 2, 30) (intermittent)",
         recur="AssertionError in test_billing_rollover: rollover_at mismatch, only fails some mornings",
         fix="Freeze the clock at a fixed UTC timestamp — the flake was the DST spring-forward gap",
         note="test_billing_rollover flaked on DST spring-forward; froze the clock at a fixed UTC timestamp."),
    dict(id="cursor", notable=False, file="app/pagination.py",
         error="KeyError: 'next_cursor' when the final page returns exactly page_size rows",
         recur="KeyError: 'next_cursor' on the last page of /orders when row count is a multiple of page_size",
         fix="Fetch page_size+1 rows to probe for more, and emit next_cursor=None on the final page",
         note="Pagination bug: last page with exactly page_size rows raised KeyError next_cursor; now probe with page_size+1 and emit None."),
    dict(id="charmap", notable=False, file="app/cli/report.py",
         error="UnicodeEncodeError: 'charmap' codec can't encode character '\\u2713' in position 12",
         recur="UnicodeEncodeError: 'charmap' codec can't encode character '\\u2713' printing the summary table",
         fix="Reconfigure stdout to UTF-8 with errors=replace before printing glyphs on Windows consoles",
         note="Windows console crashed printing check-mark glyphs; reconfigure stdout to UTF-8 (errors=replace) first."),
    dict(id="lockheld", notable=False, file="app/locking.py",
         error="Timeout: could not acquire .app/lock within 5s in test_concurrent_writes",
         recur="Timeout: could not acquire .app/lock within 5s (second run in the same session)",
         fix="Release the lock in a finally block — the earlier test left it held after an assertion failure",
         note="Lock timeout in test_concurrent_writes: a failing test left the lock held; release moved into a finally block."),
    dict(id="nplus1", notable=False, file="app/serializers.py",
         error="Slow request: GET /orders took 4.2s — 300 SELECT statements issued from OrderSerializer",
         recur="Slow request: GET /orders 3.8s, hundreds of SELECTs traced to OrderSerializer",
         fix="Add selectinload(Order.items) to the orders query — the serializer was lazy-loading per row",
         note="GET /orders was slow from N+1 lazy loads in OrderSerializer; fixed with selectinload(Order.items)."),
    dict(id="cienv", notable=False, file=".github/workflows/ci.yml",
         error="KeyError: 'STRIPE_TEST_KEY' during pytest collection in CI",
         recur="KeyError: 'STRIPE_TEST_KEY' collecting payment tests on a fork PR",
         fix="Guard the import with os.environ.get and skip payment tests when the key is absent",
         note="CI collection crashed on missing STRIPE_TEST_KEY; payment tests now skip when the env var is absent."),
    dict(id="cachedt", notable=False, file="app/cache.py",
         error="TypeError: Object of type datetime is not JSON serializable when caching the session payload",
         recur="TypeError: Object of type datetime is not JSON serializable in cache.set for sessions",
         fix="Serialize with a default=str JSON encoder before SETEX and parse ISO strings on read",
         note="Session caching blew up on datetime serialization; JSON-encode with default=str and parse ISO strings on read."),
    dict(id="dockercopy", notable=False, file="Dockerfile",
         error="ModuleNotFoundError: No module named 'app.newmod' inside the container but not locally",
         recur="ModuleNotFoundError: No module named 'app.newmod' in the deployed image only",
         fix="COPY requirements first and app/ after the pip install layer — the cached layer was hiding new modules",
         note="Container missed new modules because the COPY layer was cached; requirements now copied before app/."),
]

# Errors that were NEVER seen — neither arm should surface anything.
CONTROLS = [
    dict(id="ctrl_mem", file="app/analytics.py",
         error="MemoryError: unable to allocate 8.2 GiB for an array with shape (1048576, 1024)"),
    dict(id="ctrl_ssl", file="app/mailer.py",
         error="ssl.SSLCertVerificationError: certificate verify failed: unable to get local issuer certificate"),
]

# Auto-learn junk that passed the salience gate — the price of zero-discipline
# capture. A few deliberately reference INCIDENT files, so Rainman's ranking has
# to put the fix above same-file noise (grep's curated file has no such burden).
NOISE_POOL = [
    ("Read app/auth.py while reviewing the token refresh flow", ["app/auth.py"]),
    ("Edited app/db.py: renamed get_conn to acquire_connection", ["app/db.py"]),
    ("Tests passed: 42 passed, 1 skipped in 3.1s", []),
    ("Edited app/serializers.py: reordered the field list alphabetically", ["app/serializers.py"]),
    ("Read docs/architecture.md for the service topology overview", []),
    ("Ran black and isort across the app package, no functional change", []),
    ("Edited app/cache.py: bumped the default TTL comment", ["app/cache.py"]),
    ("Read tests/test_billing.py to check fixture usage", ["tests/test_billing.py"]),
    ("Dependency bump: requests 2.31 -> 2.32 in requirements.txt", []),
    ("Read app/webhooks.py while tracing a partner onboarding question", ["app/webhooks.py"]),
]


def seed_rainman(noise: int):
    """Build the auto-learned store: every incident as a failure->fix card pair
    through the hook's real API, notable decisions as session_end-style cards,
    plus `noise` filler cards. Returns (engine, incident_id -> {card ids})."""
    tmp = tempfile.mkdtemp(prefix="lazy_notes_")
    e = RainmanEngine(project_dir=os.path.join(tmp, "p"), global_dir=os.path.join(tmp, "g"))
    e.store.init_project(os.path.join(tmp, "p"))
    e.store.init_global()

    relevant = {}
    for inc in INCIDENTS:
        failure = e.record_failure(inc["error"], file_refs=[inc["file"]])
        solution = e.resolve_failure(failure, inc["fix"])
        ids = {failure.id, solution.id}
        if inc["notable"]:
            card = e.add(inc["note"], category="decision", source="hook:session_end")
            if card:
                ids.add(card.id)
        relevant[inc["id"]] = ids

    for i in range(noise):
        content, refs = NOISE_POOL[i % len(NOISE_POOL)]
        e.add(f"{content} (#{i})", category="note", file_refs=refs,
              source="hook:post_tool_use")

    return e, relevant


def build_notes(diligence: float):
    """The notes file a human with this diligence actually has: all notable
    write-ups, plus the first `round(diligence * n_routine)` routine notes
    (deterministic — no sampling). Returns [(incident_id, text, order)]."""
    routine = [i for i in INCIDENTS if not i["notable"]]
    n_kept = int(round(diligence * len(routine)))
    kept_routine = {i["id"] for i in routine[:n_kept]}
    notes, order = [], 0
    for inc in INCIDENTS:
        if inc["notable"] or inc["id"] in kept_routine:
            notes.append((inc["id"], inc["note"], order))
            order += 1
    return notes


# --- the two retrievers -------------------------------------------------------
_WORD = re.compile(r"\w+")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "in", "on", "of", "to", "for", "and", "with",
    "not", "but", "at", "by", "was", "were", "type", "object", "during", "when",
    "only", "some", "from", "no", "named", "get",
}


def grep_notes(notes, error_text: str, k: int):
    """Fair grep over the notes file: whole-word match on the error's
    distinctive terms (stopwords stripped, as a human would search), ranked by
    distinct terms matched then recency. Returns ordered incident ids."""
    terms = {t for t in _WORD.findall(error_text.lower())
             if len(t) > 2 and t not in _STOPWORDS and not t.isdigit()}
    scored = []
    for inc_id, text, recency in notes:
        low = text.lower()
        hits = sum(1 for t in terms if re.search(rf"\b{re.escape(t)}\b", low))
        if hits:
            scored.append((hits, recency, inc_id))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [inc_id for _, _, inc_id in scored[:k]]


def rainman_recall(engine, error_text: str, file: str, k: int):
    """Error-conditioned recall, the way a hook calls it when an error recurs:
    no hand-written query, just the task state."""
    results = engine.recall("", context_files=[file], error_signature=error_text,
                            limit=k)
    return [r.memory.id for r in results]


# --- measurement ---------------------------------------------------------------
def run(noise: int, diligence_sweep, k: int = 5):
    engine, relevant = seed_rainman(noise)
    store_size = len(engine._memories)

    # Rainman arm: independent of diligence — measure once.
    rain_rows, rain_hits, rain_ranks = [], 0, []
    for inc in INCIDENTS:
        ids = rainman_recall(engine, inc["recur"], inc["file"], k)
        rank = next((i + 1 for i, mid in enumerate(ids) if mid in relevant[inc["id"]]), None)
        hit = rank is not None
        rain_hits += hit
        if hit:
            rain_ranks.append(rank)
        rain_rows.append({"incident": inc["id"], "notable": inc["notable"],
                          "hit": hit, "rank": rank, "ids": ids})

    rain_controls = []
    for ctrl in CONTROLS:
        ids = rainman_recall(engine, ctrl["error"], ctrl["file"], k)
        rain_controls.append({"control": ctrl["id"], "surfaced": len(ids),
                              "clean": len(ids) == 0, "ids": ids})

    # Notes arm: one cell per diligence level.
    cells = []
    for diligence in diligence_sweep:
        notes = build_notes(diligence)
        present = {nid for nid, _, _ in notes}
        rows, hits, cov_hits = [], 0, 0
        for inc in INCIDENTS:
            got = grep_notes(notes, inc["recur"], k)
            hit = inc["id"] in got
            hits += hit
            cov_hits += hit and inc["id"] in present
            rows.append({"incident": inc["id"], "recorded": inc["id"] in present,
                         "hit": hit, "ids": got})
        ctrl_rows = []
        for ctrl in CONTROLS:
            got = grep_notes(notes, ctrl["error"], k)
            ctrl_rows.append({"control": ctrl["id"], "surfaced": len(got),
                              "clean": len(got) == 0, "ids": got})
        cells.append({
            "diligence": diligence,
            "notes_kept": len(notes),
            "coverage": len(present) / len(INCIDENTS),
            "end_to_end": hits / len(INCIDENTS),
            "retrieval_given_coverage": (cov_hits / len(present)) if present else None,
            "rows": rows,
            "controls": ctrl_rows,
        })

    return {
        "k": k,
        "noise": noise,
        "incidents": len(INCIDENTS),
        "notable": sum(1 for i in INCIDENTS if i["notable"]),
        "rainman_store_size": store_size,
        "rainman": {
            "end_to_end": rain_hits / len(INCIDENTS),
            "mean_rank_of_fix": (sum(rain_ranks) / len(rain_ranks)) if rain_ranks else None,
            "rows": rain_rows,
            "controls": rain_controls,
        },
        "notes_cells": cells,
    }


# --- presentation ----------------------------------------------------------------
def _pct(x):
    return f"{round(100 * x):3d}%"


def _print(report):
    n = report["incidents"]
    print(f"{n} incidents ({report['notable']} notable, {n - report['notable']} routine), "
          f"error recurs later; hit = fix in top-{report['k']}  (deterministic, no LLM)")
    print(f"Rainman store: {report['rainman_store_size']} memories "
          f"(incl. {report['noise']} auto-learn noise cards); notes file: curated, noise-free\n")

    print(f"{'human diligence on routine fixes':36} {'coverage':>9} {'grep notes':>11} "
          f"{'given-coverage':>15}")
    print("-" * 76)
    for cell in report["notes_cells"]:
        rgc = cell["retrieval_given_coverage"]
        print(f"{_pct(cell['diligence']):>7} ({cell['notes_kept']:2d} notes on file){'':11} "
              f"{_pct(cell['coverage']):>9} {_pct(cell['end_to_end']):>11} "
              f"{(_pct(rgc) if rgc is not None else '  n/a'):>15}")

    r = report["rainman"]
    mean_rank = f"{r['mean_rank_of_fix']:.1f}" if r["mean_rank_of_fix"] else "n/a"
    print("-" * 76)
    print(f"{'Rainman (auto-learn, error-conditioned recall)':36} {_pct(1.0):>9} "
          f"{_pct(r['end_to_end']):>11} {'(mean rank ' + mean_rank + ')':>15}")

    misses = [row["incident"] for row in r["rows"] if not row["hit"]]
    if misses:
        print(f"\nRainman honest misses (card stored but not surfaced): {misses}")

    ctrl_clean_rain = all(c["clean"] for c in r["controls"])
    ctrl_clean_grep = all(c["clean"] for cell in report["notes_cells"] for c in cell["controls"])
    print(f"\ncontrol errors (never seen): "
          f"grep {'surfaced nothing' if ctrl_clean_grep else 'SURFACED SOMETHING'} | "
          f"Rainman {'surfaced nothing' if ctrl_clean_rain else 'SURFACED SOMETHING'}")
    if not ctrl_clean_rain:
        for c in r["controls"]:
            if not c["clean"]:
                print(f"  Rainman surfaced {c['surfaced']} result(s) for {c['control']}")

    print("\nreading: end-to-end = coverage x retrieval-given-coverage. Grep retrieves what")
    print("was written down nearly perfectly — its ceiling is what the human wrote down.")
    print("(Synthetic, small-N; Rainman coverage is conditional on the hook capturing —")
    print(" see SCOPE HONESTY in the module docstring.)")


def _print_contexts(report):
    print("== Rainman (error-conditioned) ==")
    for row in report["rainman"]["rows"]:
        print(f"  {row['incident']:10} hit={row['hit']} rank={row['rank']} ids={row['ids']}")
    for cell in report["notes_cells"]:
        print(f"== grep notes @ diligence {cell['diligence']:.2f} ==")
        for row in cell["rows"]:
            print(f"  {row['incident']:10} recorded={row['recorded']} hit={row['hit']} ids={row['ids']}")


def main(argv=None):
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()

    ap = argparse.ArgumentParser(description="Rainman vs the notes a real human keeps")
    ap.add_argument("--noise", type=int, default=60,
                    help="auto-learn noise cards in Rainman's store (default 60)")
    ap.add_argument("-k", type=int, default=5, help="top-k retrieved (default 5)")
    ap.add_argument("--diligence", type=float, action="append",
                    help="routine-fix note-taking rate(s) to test (default 0 1/3 2/3 1)")
    ap.add_argument("--contexts", action="store_true", help="show what each side surfaced")
    ap.add_argument("--json", metavar="PATH", help="write the full report as JSON")
    a = ap.parse_args(argv)

    sweep = a.diligence if a.diligence else [0.0, 1 / 3, 2 / 3, 1.0]
    report = run(a.noise, sweep, k=a.k)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"wrote {a.json}")
    if a.contexts:
        _print_contexts(report)
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
