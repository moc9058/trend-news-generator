"""Read-only inspector for the M1 acceptance drill (docs/plans/m1-acceptance-drill.md).

Usage:  cd pipeline && RUN=rr_... uv run python scripts/drill_inspect.py
Prints the run's status/phase/budget, checkpoint counts, and phase_start tally.
Reads only — never writes. Needs ADC (gcloud auth) and the app package installed.
"""
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
ckpts = sum(1 for _ in doc.collection("checkpoints").stream())
writes = sum(1 for _ in doc.collection("checkpoint_writes").stream())
print(f"checkpoints={ckpts}  checkpoint_writes={writes}")
starts = collections.Counter(
    e.to_dict().get("phase") for e in doc.collection("events").stream()
    if e.to_dict().get("action") == "phase_start")
print("phase_start counts:", dict(starts) or "(none)")
