# M1 acceptance drill — Research Agent on LangGraph

> One-time human verification of the M1 migration (commit `f192157`). Everything
> automated is already green (332 tests, admin typecheck, deps pinned, prod at
> 2Gi/cpu2). This drill covers the two things a test suite cannot: the
> plan-approval interrupt/resume across two job executions, and crash-recovery
> from a Firestore checkpoint. Plan reference: `langgraph-migration-plan.md` §6 M1.

**What M1 fundamentally fixes:** the old harness re-ran the *last completed phase*
on resume, and because `draft`/`localized`/`selected` were not persisted, a crash
after `write` could make `review` run on empty context and mint an empty Post.
LangGraph checkpoints (superstep granularity) make resume continue from the exact
point of interruption instead. Drill B is what proves that in production.

## Fixtures

- **Admin UI:** https://admin-ui-lqkvvk6ewq-an.a.run.app (behind IAP; sign in as `moc9058@gmail.com`)
- **Job / region:** `job-generate-report` / `asia-northeast1`
- **Firestore run doc:** `researchRuns/{runId}` with subcollections `events`, `checkpoints`, `checkpoint_writes`
- **LangSmith:** https://smith.langchain.com → project `trend-news-generator`
- Have a terminal with `gcloud` authed to `trend-news-generator` (already is).

Set shell vars as you go so the commands are copy-paste (run the `python`
snippets from `pipeline/`):
```bash
REGION=asia-northeast1
export RUN=      # fill in with the runId once you launch (e.g. rr_20260716_xxxx)
```

### The inspector snippet (used throughout)
There is **no** `gcloud firestore documents` command, so read the run doc through
the app's own repo layer. Save this once as `pipeline/scripts/drill_inspect.py`
(read-only — it only reads):
```python
import os, collections
from app.repo.research import db, COLLECTION, get
RUN = os.environ["RUN"]
run = get(RUN)
doc = db().collection(COLLECTION).document(RUN)
if run:
    b = run.budget
    print(f"status={run.status}  phase={run.phase}  planApproved={run.planApproved}  "
          f"postId={run.postId or '-'}  usdSpent={b.usdSpent}  loops={run.loops}")
else:
    print("run doc not found:", RUN)
ckpts  = sum(1 for _ in doc.collection("checkpoints").stream())
writes = sum(1 for _ in doc.collection("checkpoint_writes").stream())
print(f"checkpoints={ckpts}  checkpoint_writes={writes}")
starts = collections.Counter(
    e.to_dict().get("phase") for e in doc.collection("events").stream()
    if e.to_dict().get("action") == "phase_start")
print("phase_start counts:", dict(starts) or "(none)")
```
Run it any time with:
```bash
cd pipeline && uv run python scripts/drill_inspect.py
```
(Needs ADC — you already have `gcloud` auth. The admin **Research → run detail**
page shows the same status/phase/flow visually; use whichever you prefer. The Post
body and localizations are easiest to read in admin or the Firestore console.)

---

## Drill A — plan-approval interrupt & resume (happy path)

Proves: the graph pauses at an `interrupt()`, the pause survives as a checkpoint,
approval resumes the *same* thread in a second job execution (not a fresh run),
and the checkpoint is torn down on success.

### A1. Launch with the approval gate on
In admin → **Research** → the launcher form:
- **theme:** a short concrete theme (or blank to auto-select)
- **budgetUsd:** `2` (this cap is what bounds the cost; the form has no depth control — depth defaults to `standard`)
- **planApproval:** ✅ **checked** ← this is the gate under test

Submit. The API returns `202 {runId, accepted}` and triggers the job. Grab the
`runId` (visible in the run list / detail URL) into `RUN`.

### A2 + A3. It should stop at the plan gate, with a checkpoint
Within a minute or two, `uv run python scripts/drill_inspect.py` should show:
```
status=awaiting_plan_approval  phase=gather  planApproved=False  postId=-  usdSpent=... loops=0
checkpoints=1  checkpoint_writes=...
phase_start counts: {'plan': 1}
```
- **status `awaiting_plan_approval`, phase `gather`** — the interrupt is raised at
  the plan gate, before gather runs.
- **`checkpoints >= 1`** — the pause is durable (this is what makes resume work).

In the admin **ResearchFlow** card you should see the 6-node flow with `plan` done
and the run parked before `gather`.

### A4. Approve → it resumes to the end
Click **Approve plan** in admin (this calls `POST /api/research/runs/{id}/approve-plan`,
which sets `planApproved=true`, `status=queued`, and re-triggers the job).

> Guard worth knowing: approving anything not in `awaiting_plan_approval` returns
> `409` — so a double-click or stale tab can't corrupt state.

The second job execution claims the run and **resumes** through
gather→extract→verify→write→review, ending at **`awaiting_review`** with a
`postId`. When it finishes, `drill_inspect.py` should show:
```
status=awaiting_review  phase=review  planApproved=True  postId=post_...  usdSpent<=2.0 ...
checkpoints=0  checkpoint_writes=0
phase_start counts: {'plan': 1, 'gather': 1, 'extract': 1, 'verify': 1, 'write': 1, 'review': 1}
```
This one readout covers A4–A6 at once:
- **A4** status `awaiting_review` + a `postId`, `usdSpent ≤ 2`. Open the draft Post
  (admin or Firestore console): all three localizations (`ja`/`ko`/`en`) present
  and non-empty.
- **A5 (the point):** approval did **not** replan — **`plan` appears once** in
  `phase_start counts`. Cross-check in LangSmith: a single `planner` LLM call
  across both executions.
- **A6:** on reaching `awaiting_review` the runner calls `delete_thread(runId)`, so
  **`checkpoints=0` and `checkpoint_writes=0`** (evidence/claims/events remain —
  only checkpoints are reaped).

### A7. LangSmith grouping & tags
In LangSmith:
- A root trace named **`research:<runId>`** with the graph → node spans → nested OpenAI generations.
- **Threads** view groups **both** executions (pre- and post-approval) under one thread — they share `session_id = runId`.
- Tags present: `research`, `format:report`, `trigger:manual`.

✅ **Drill A passes when:** paused at `awaiting_plan_approval`/`gather`, checkpoint
appeared, approval resumed to `awaiting_review`, plan ran once, checkpoints gone,
`usdSpent ≤ 2`, LangSmith shows one thread with the nested trace.

---

## Drill B — crash recovery from checkpoint

Proves the core M1 fix: a mid-run crash resumes from the last completed superstep
instead of re-running completed phases (and never mints an empty Post).

### B1. Launch a plain run
Same launcher, **budgetUsd `2`**, **planApproval unchecked**. Capture `RUN`.

### B2. Kill it mid-flight
Watch for it to enter `extract` (admin flow card, or poll the doc), then cancel
the *running execution* — this is a hard kill of the container, standing in for a
crash (not a graceful cancel):
```bash
EXEC=$(gcloud run jobs executions list --job=job-generate-report --region=$REGION \
        --format="value(name)" --limit=1)
gcloud run jobs executions cancel "$EXEC" --region=$REGION
```

The run is now mid-way; its `status` is left non-terminal and the last completed
superstep is durable in `checkpoints` (durability="sync"). `drill_inspect.py`
should show **`checkpoints >= 1`** and a partial `phase_start counts` (e.g. `plan`
and `gather` done, `extract` in progress).

### B3. Re-execute the job → it resumes
```bash
gcloud run jobs execute job-generate-report --region=$REGION
```
`claim_next` re-acquires the same run (queued, or `running` with stale heartbeat)
and the runner calls `graph.stream(None, config)` — continue, not restart.

### B4 + B5. Prove completed phases did NOT re-run, and it finished clean
Each phase emits exactly one `phase_start` per pass. If resume had restarted from
the top, a phase completed before the kill would show a **second** `phase_start`.
After completion, `drill_inspect.py` should show:
```
status=awaiting_review  phase=review  postId=post_...  loops=0
checkpoints=0  checkpoint_writes=0
phase_start counts: {'plan': 1, 'gather': 1, 'extract': 1, 'verify': 1, 'write': 1, 'review': 1}
```
- **The core assertion:** the phases that completed before the kill (e.g. `plan`,
  `gather`) still show **`phase_start` = 1**, not 2 — they were not re-run.
  - Caveat: a legitimate `verify→gather` coverage loop also produces a second
    `gather`/`extract`/`verify` `phase_start` and increments `loops`. So read this
    together with `loops`: extra `phase_start`s with `loops=0` = a resume bug;
    with `loops>=1` = a normal coverage loop.
- Open the Post: **`localizations.ja.body` non-empty** — this is the exact empty-Post
  bug M1 eliminates. `checkpoints=0` again (torn down on success).

✅ **Drill B passes when:** after kill+re-execute the run reaches `awaiting_review`,
no completed phase shows a duplicate `phase_start`, and the Post body is non-empty.

---

## Drill C — admin cancel (graceful)

Quick check that the cooperative cancel path still works post-migration.

1. Launch a plain `budgetUsd 2` run; while it's running click **Cancel** in admin
   (sets `cancelRequested=true`).
2. The runner checks `cancelRequested` before the graph and between supersteps, so
   it stops at the next boundary and sets **`status cancelled`** — `drill_inspect.py`
   shows `status=cancelled`.
3. The checkpoint is deliberately **left** (TTL reaps it in 14 days) so the partial
   run stays inspectable — so a non-zero `checkpoints` count here is expected, not
   a leak.

---

## If something fails

- **Never reaches `awaiting_plan_approval`:** read the job logs for an import error
  — that would mean the prod image can't load `graph/`/`langgraph`:
  ```bash
  gcloud logging read \
    'resource.type="cloud_run_job" AND resource.labels.job_name="job-generate-report"' \
    --freshness=1h --limit=50 --format="value(jsonPayload.message, textPayload)"
  ```
- **Resume restarts from the top (`phase_start` = 2 with `loops=0`):** the
  checkpoint wasn't read — re-check `checkpoints` right after the kill (B2). Empty
  there means `put` didn't durably land; capture the runId and the logs above.
- **Empty Post body:** the regression M1 targets — capture runId, `events`, and the
  Post doc before retrying; do not delete the run.
- General research-run recovery guidance: `docs/runbook.md` → "Research Agent（レポート）の失敗対応".

Budget note: each full run here spends up to its `$2` cap; three drills ≈ under
$10 total, well inside the report budget.
