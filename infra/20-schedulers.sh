#!/usr/bin/env bash
# Cloud Scheduler → Cloud Run Jobs (OAuth), all in Asia/Tokyo.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

grant_invoker() {
  gcloud run jobs add-iam-policy-binding "$1" --region="$REGION" \
    --member="serviceAccount:${SCHEDULER_SA}" --role=roles/run.invoker -q >/dev/null
}

create_sched() {
  local name="$1" cron="$2" job="$3"
  grant_invoker "$job"
  local uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${job}:run"
  gcloud scheduler jobs create http "$name" \
    --location="$REGION" \
    --schedule="$cron" --time-zone="Asia/Tokyo" \
    --uri="$uri" --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA" 2>/dev/null \
  || gcloud scheduler jobs update http "$name" \
    --location="$REGION" \
    --schedule="$cron" --time-zone="Asia/Tokyo" \
    --uri="$uri" --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA"
}

# The report trigger calls pipeline-api DIRECTLY (not a job:run), so it uses an
# OIDC ID token whose audience is the pipeline-api service URL (docs 10 §4.6).
PIPELINE_API_URL="$(gcloud run services describe pipeline-api --region="$REGION" \
  --format='value(status.url)' 2>/dev/null || true)"

create_sched_oidc() {
  local name="$1" cron="$2" path="$3"
  if [[ -z "$PIPELINE_API_URL" ]]; then
    echo "!! pipeline-api URL not found — run 10-deploy-pipeline.sh first. Skipping $name"
    return
  fi
  # scheduler-sa must be allowed to invoke the private (--no-allow-unauthenticated) service.
  gcloud run services add-iam-policy-binding pipeline-api --region="$REGION" \
    --member="serviceAccount:${SCHEDULER_SA}" --role=roles/run.invoker -q >/dev/null
  local uri="${PIPELINE_API_URL}${path}"
  gcloud scheduler jobs create http "$name" \
    --location="$REGION" \
    --schedule="$cron" --time-zone="Asia/Tokyo" \
    --uri="$uri" --http-method=POST \
    --headers="Content-Type=application/json" --message-body='{"trigger":"scheduled"}' \
    --oidc-service-account-email="$SCHEDULER_SA" \
    --oidc-token-audience="$PIPELINE_API_URL" 2>/dev/null \
  || gcloud scheduler jobs update http "$name" \
    --location="$REGION" \
    --schedule="$cron" --time-zone="Asia/Tokyo" \
    --uri="$uri" --http-method=POST \
    --headers="Content-Type=application/json" --message-body='{"trigger":"scheduled"}' \
    --oidc-service-account-email="$SCHEDULER_SA" \
    --oidc-token-audience="$PIPELINE_API_URL"
}

create_sched sched-collect            "0 6 * * *"  job-collect
create_sched sched-generate-short     "0 8 * * *"  job-generate-short
create_sched sched-generate-article   "0 7 * * 1"  job-generate-article
create_sched sched-cleanup-drafts     "0 4 * * *"  job-cleanup-drafts
create_sched sched-threads-refresh    "0 3 * * 1"  job-refresh-threads-token

# Monthly deep-dive report: POST /api/research/runs with an empty theme → the
# Harness auto-selects a theme (R1). pipeline-api returns 202 and the queued run
# is picked up by job-generate-report.
create_sched_oidc sched-generate-report "0 7 1 * *" "/api/research/runs"

echo "schedulers created (Asia/Tokyo): 06:00 collect / 08:00 short / Mon 07:00 article / 1st 07:00 report / 04:00 cleanup drafts / Mon 03:00 token refresh"
