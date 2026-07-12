#!/usr/bin/env bash
# One-shot Cloud deployment: chains the infra/ scripts so a full (re)deploy is
# a single command instead of running each numbered script by hand.
#
#   00-bootstrap.sh -> [01-secrets.sh] -> 10-deploy-pipeline.sh -> job-seed
#   -> 11-deploy-admin.sh -> 20-schedulers.sh
#
# 01-secrets.sh is interactive (prompts for API keys) and is SKIPPED by
# default so this script can run unattended; pass --with-secrets to include
# it, or run `infra/01-secrets.sh` by hand once (or when rotating a key).
set -euo pipefail
cd "$(dirname "$0")/infra"
source ./env.sh

with_secrets=0
skip_bootstrap=0
skip_seed=0
skip_schedulers=0

usage() {
  cat <<EOF
Usage: ./deploy.sh [options]

Runs the full deploy chain non-interactively:
  1. 00-bootstrap.sh       (idempotent; APIs, Firestore, GCS, SAs, IAM)
  2. 01-secrets.sh         (interactive; SKIPPED by default)
  3. 10-deploy-pipeline.sh (build + deploy pipeline-api + jobs)
  4. job-seed              (idempotent create-only initial data)
  5. 11-deploy-admin.sh    (build + deploy admin UI behind IAP)
  6. 20-schedulers.sh      (Cloud Scheduler wiring)

Options:
  --with-secrets      also run 01-secrets.sh (interactive prompts)
  --skip-bootstrap    skip 00-bootstrap.sh (use for routine redeploys)
  --skip-seed         skip the job-seed execution
  --skip-schedulers   skip 20-schedulers.sh
  -h, --help          show this help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --with-secrets) with_secrets=1 ;;
    --skip-bootstrap) skip_bootstrap=1 ;;
    --skip-seed) skip_seed=1 ;;
    --skip-schedulers) skip_schedulers=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

gcloud config set project "$PROJECT_ID" >/dev/null

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
