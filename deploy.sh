#!/usr/bin/env bash
# One-shot Cloud deployment: chains the infra/ scripts so a full (re)deploy is
# a single command instead of running each numbered script by hand.
#
#   00-bootstrap.sh -> [01-secrets.sh] -> 10-deploy-pipeline.sh -> job-seed
#   -> 11-deploy-admin.sh -> 20-schedulers.sh
#
# --migrate runs the cadence->format migration (docs/runbook.md 「区分リネーム移行」)
# in the safe order: backup -> indexes -> PAUSE schedulers -> deploy -> migrate
# (dry-run then apply) -> admin -> schedulers -> RESUME -> delete orphans. Use it
# once to roll the rename onto an existing environment; a plain ./deploy.sh only
# ships code/infra and must NOT be used alone for the rename.
#
# 01-secrets.sh is interactive (prompts for API keys) and is SKIPPED by default;
# pass --with-secrets to include it, or run infra/01-secrets.sh by hand.
set -euo pipefail
cd "$(dirname "$0")/infra"
source ./env.sh

with_secrets=0
skip_bootstrap=0
skip_seed=0
skip_schedulers=0
migrate=0
assume_yes=0
skip_backup=0

usage() {
  cat <<EOF
Usage: ./deploy.sh [options]

Default (code/infra only) chain:
  1. 00-bootstrap.sh       (idempotent; APIs, Firestore indexes, GCS, SAs, IAM)
  2. 01-secrets.sh         (interactive; SKIPPED by default)
  3. 10-deploy-pipeline.sh (build + deploy pipeline-api + 7 jobs incl generate-report)
  4. job-seed              (idempotent create-only initial data)
  5. 11-deploy-admin.sh    (build + deploy admin UI behind IAP)
  6. 20-schedulers.sh      (Cloud Scheduler wiring incl OIDC sched-generate-report)

--migrate (cadence -> format rename on an EXISTING environment) reorders to the
safe migration sequence and additionally: backs up Firestore, PAUSES the old
schedulers before deploy, runs scripts/migrate_cadence_to_format.py (dry-run then
--apply --notion), RESUMES the unchanged schedulers, and deletes the orphaned
job/sched-generate-{daily,weekly,monthly}. Destructive steps prompt unless --yes.

Options:
  --migrate           run the cadence->format migration rollout (see runbook §9.2)
  -y, --yes           auto-confirm the migration apply + orphan deletion (unattended)
  --skip-backup       (migrate only) skip the Firestore export backup
  --with-secrets      also run 01-secrets.sh (interactive prompts)
  --skip-bootstrap    skip 00-bootstrap.sh (routine redeploys)
  --skip-seed         skip the job-seed execution
  --skip-schedulers   skip 20-schedulers.sh (non-migrate mode only)
  -h, --help          show this help

The migration step runs Python from pipeline/ (needs google-cloud-firestore +
the app package installed and ADC). Override the interpreter with PYTHON=... ;
by default it prefers pipeline/.venv/bin/python, else python3.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --migrate) migrate=1 ;;
    -y|--yes) assume_yes=1 ;;
    --skip-backup) skip_backup=1 ;;
    --with-secrets) with_secrets=1 ;;
    --skip-bootstrap) skip_bootstrap=1 ;;
    --skip-seed) skip_seed=1 ;;
    --skip-schedulers) skip_schedulers=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

gcloud config set project "$PROJECT_ID" >/dev/null

# ---- migration helpers -------------------------------------------------------

# Old cadence-era resources to pause/delete during the rename. (Resuming/enabling
# is handled by 20-schedulers.sh, which ensures ALL schedulers end ENABLED.)
OLD_SCHEDS=(sched-collect sched-generate-daily sched-generate-weekly \
            sched-generate-monthly sched-cleanup-drafts)
ORPHAN_SCHEDS=(sched-generate-daily sched-generate-weekly sched-generate-monthly)
ORPHAN_JOBS=(job-generate-daily job-generate-weekly job-generate-monthly)

pause_scheds()  { for s in "$@"; do gcloud scheduler jobs pause  "$s" --location="$REGION" -q 2>/dev/null && echo "  paused $s"  || echo "  (skip $s — not found)"; done; }
delete_scheds() { for s in "$@"; do gcloud scheduler jobs delete "$s" --location="$REGION" -q 2>/dev/null && echo "  deleted $s" || echo "  (skip $s — not found)"; done; }
delete_jobs()   { for j in "$@"; do gcloud run jobs delete       "$j" --region="$REGION"   -q 2>/dev/null && echo "  deleted $j" || echo "  (skip $j — not found)"; done; }

pick_python() {
  if [[ -n "${PYTHON:-}" ]]; then echo "$PYTHON";
  elif [[ -x ../pipeline/.venv/bin/python ]]; then echo "../pipeline/.venv/bin/python";
  else echo python3; fi
}
run_migrate() { ( cd ../pipeline && "$(pick_python)" -m scripts.migrate_cadence_to_format "$@" ); }

confirm() {  # $1 = prompt. Returns 0 (yes) automatically when --yes given.
  [[ "$assume_yes" == 1 ]] && return 0
  local ans; read -r -p "$1 [y/N] " ans; [[ "$ans" == [yY] ]]
}

# ---- migration rollout -------------------------------------------------------

if [[ "$migrate" == 1 ]]; then
  echo "=== MIGRATION DEPLOY: cadence -> format (runbook §9.2) ==="

  py="$(pick_python)"
  if ! ( cd ../pipeline && "$py" -c "import google.cloud.firestore, app.models" ) 2>/dev/null; then
    echo "!! '$py' cannot import google-cloud-firestore + the app package." >&2
    echo "   Set up the pipeline env first (cd pipeline && pip install -e '.[dev]')" >&2
    echo "   and authenticate ADC (gcloud auth application-default login), or set PYTHON=..." >&2
    exit 1
  fi

  if [[ "$skip_backup" == 0 ]]; then
    ts="$(date +%Y%m%d-%H%M%S)"
    echo "=== [1/9] backup Firestore -> gs://${BUCKET}/backups/pre-format-${ts} ==="
    gcloud firestore export "gs://${BUCKET}/backups/pre-format-${ts}"
  else
    echo "=== [1/9] backup: skipped (--skip-backup) ==="
  fi

  if [[ "$skip_bootstrap" == 0 ]]; then
    echo "=== [2/9] bootstrap (creates format + researchRuns indexes first; async) ==="
    ./00-bootstrap.sh
  else
    echo "=== [2/9] bootstrap: skipped (--skip-bootstrap) ==="
  fi

  echo "=== [3/9] pause schedulers (so old jobs don't run against migrating data) ==="
  pause_scheds "${OLD_SCHEDS[@]}"

  echo "=== [4/9] deploy pipeline (new image + jobs; old jobs kept for rollback) ==="
  ./10-deploy-pipeline.sh

  echo "=== [5/9] migration dry-run ==="
  run_migrate --dry-run
  if confirm "Apply the migration now (--apply --notion)?"; then
    run_migrate --apply --notion \
      || { echo "!! migration failed — schedulers left PAUSED. Fix, then re-run or resume manually." >&2; exit 1; }
  else
    echo "!! migration NOT applied. Schedulers left PAUSED. Re-run with --yes, or apply by hand then resume." >&2
    exit 1
  fi

  if [[ "$skip_seed" == 0 ]]; then
    echo "=== [6/9] seed (idempotent; fills any missing report configs) ==="
    gcloud run jobs execute job-seed --region "$REGION" --wait
  else
    echo "=== [6/9] seed: skipped (--skip-seed) ==="
  fi

  echo "=== [7/9] admin ui (rebuild syncs shared-constants + ships Research UI) ==="
  ./11-deploy-admin.sh

  echo "=== [8/9] schedulers (create short/article/report; ensure ALL enabled) ==="
  ./20-schedulers.sh

  echo "=== [9/9] orphaned cadence-era jobs & schedulers ==="
  if confirm "Delete orphaned generate-{daily,weekly,monthly} job+scheduler?"; then
    delete_scheds "${ORPHAN_SCHEDS[@]}"
    delete_jobs "${ORPHAN_JOBS[@]}"
  else
    echo "  (kept for rollback — delete later, runbook step 9)"
  fi

  echo ""
  echo "migration deploy complete. REMAINING MANUAL STEPS (runbook step 10):"
  echo "  - smoke test: trigger a short run + one research run; verify admin grids & 3-lang draft"
  echo "  - after verification, drop the old posts(cadence,createdAt) composite index"
  exit 0
fi

# ---- default (code/infra only) chain -----------------------------------------

if [[ "$skip_bootstrap" == 1 ]]; then
  echo "=== [1/6] bootstrap: skipped (--skip-bootstrap) ==="
else
  echo "=== [1/6] bootstrap ==="
  ./00-bootstrap.sh
fi

if [[ "$with_secrets" == 1 ]]; then
  echo "=== [2/6] secrets (interactive) ==="
  ./01-secrets.sh
else
  echo "=== [2/6] secrets: skipped (interactive; pass --with-secrets to include, or run ./infra/01-secrets.sh by hand) ==="
fi

echo "=== [3/6] pipeline (build + deploy service + jobs) ==="
./10-deploy-pipeline.sh

if [[ "$skip_seed" == 1 ]]; then
  echo "=== [4/6] seed: skipped (--skip-seed) ==="
else
  echo "=== [4/6] seed (idempotent, create-only) ==="
  gcloud run jobs execute job-seed --region "$REGION" --wait
fi

echo "=== [5/6] admin ui ==="
./11-deploy-admin.sh

if [[ "$skip_schedulers" == 1 ]]; then
  echo "=== [6/6] schedulers: skipped (--skip-schedulers) ==="
else
  echo "=== [6/6] schedulers ==="
  ./20-schedulers.sh
fi

echo "deploy complete."
