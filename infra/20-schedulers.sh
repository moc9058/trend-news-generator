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
create_sched sched-generate-daily     "0 8 * * *"  job-generate-daily
create_sched sched-generate-weekly    "0 7 * * 1"  job-generate-weekly
create_sched sched-generate-monthly   "0 7 1 * *"  job-generate-monthly
create_sched sched-threads-refresh    "0 3 * * 1"  job-refresh-threads-token

echo "schedulers created (Asia/Tokyo): 06:00 collect / 08:00 daily / Mon 07:00 weekly / 1st 07:00 monthly / Mon 03:00 token refresh"
