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

create_sched sched-collect            "0 6 * * *"  job-collect
create_sched sched-generate-short     "0 8 * * *"  job-generate-short
create_sched sched-generate-article   "0 7 * * 1"  job-generate-article
create_sched sched-cleanup-drafts     "0 4 * * *"  job-cleanup-drafts
create_sched sched-threads-refresh    "0 3 * * 1"  job-refresh-threads-token

# The 1st-of-month report trigger (sched-generate-report) calls pipeline-api
# directly (OIDC), not a Cloud Run Job, so it is added by a later phase (docs 10 §4.6 / §9.1 P7).

echo "schedulers created (Asia/Tokyo): 06:00 collect / 08:00 short / Mon 07:00 article / 04:00 cleanup drafts / Mon 03:00 token refresh"
