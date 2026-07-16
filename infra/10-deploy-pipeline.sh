#!/usr/bin/env bash
# Build the single pipeline image, deploy pipeline-api (service) + 6 jobs.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

echo "--- build image via Cloud Build"
gcloud builds submit ../pipeline --tag "$IMAGE" --region="$REGION"

SECRETS=(openai-api-key gemini-api-key x-credentials threads-access-token \
         threads-user-id notion-api-key)
SECRET_ENV="OPENAI_API_KEY=openai-api-key:latest"
SECRET_ENV+=",GEMINI_API_KEY=gemini-api-key:latest"
SECRET_ENV+=",X_CREDENTIALS=x-credentials:latest"
SECRET_ENV+=",THREADS_ACCESS_TOKEN=threads-access-token:latest"
SECRET_ENV+=",THREADS_USER_ID=threads-user-id:latest"
SECRET_ENV+=",NOTION_API_KEY=notion-api-key:latest"
if gcloud secrets describe ieee-api-key >/dev/null 2>&1; then
  SECRET_ENV+=",IEEE_API_KEY=ieee-api-key:latest"
  SECRETS+=(ieee-api-key)
fi
# optional: Semantic Scholar key (research academic connector; falls back to
# OpenAlex/Crossref without it).
if gcloud secrets describe semantic-scholar-api-key >/dev/null 2>&1; then
  SECRET_ENV+=",SEMANTIC_SCHOLAR_API_KEY=semantic-scholar-api-key:latest"
  SECRETS+=(semantic-scholar-api-key)
fi

COMMON_ENV="PROJECT_ID=${PROJECT_ID},REGION=${REGION},GCS_BUCKET=${BUCKET},PIPELINE_SERVICE_ACCOUNT=${PIPELINE_SA}"

# optional: LangSmith tracing. The secret's existence is the on/off switch — to
# disable, delete/disable the secret and redeploy (env is fully replaced below).
# Endpoint is left unset (= US SaaS).
if gcloud secrets describe langsmith-api-key >/dev/null 2>&1; then
  SECRET_ENV+=",LANGSMITH_API_KEY=langsmith-api-key:latest"
  COMMON_ENV+=",LANGSMITH_TRACING=true,LANGSMITH_PROJECT=${PROJECT_ID}"
  SECRETS+=(langsmith-api-key)
fi

# Grants live here, next to the mount, NOT in 01-secrets.sh: that script is
# interactive and ./deploy.sh skips it by default, so a grant placed there never
# runs on a routine deploy and the revision fails to start on a secret added
# since the last hand-run of 01. Every add-iam-policy-binding is idempotent.
echo "--- grant pipeline-sa read access to the mounted secrets"
for s in "${SECRETS[@]}"; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${PIPELINE_SA}" --role=roles/secretmanager.secretAccessor -q >/dev/null
done
# refresh-threads-token rotates the token in place: add a version, disable the old
for role in secretVersionAdder secretVersionManager; do
  gcloud secrets add-iam-policy-binding threads-access-token \
    --member="serviceAccount:${PIPELINE_SA}" --role="roles/secretmanager.${role}" -q >/dev/null
done

echo "--- deploy pipeline-api (private service)"
gcloud run deploy pipeline-api \
  --image="$IMAGE" --region="$REGION" \
  --service-account="$PIPELINE_SA" \
  --no-allow-unauthenticated \
  --memory=512Mi --cpu=1 --max-instances=2 --timeout=900 \
  --set-env-vars="$COMMON_ENV" \
  --set-secrets="$SECRET_ENV"

# admin-sa may invoke pipeline-api
gcloud run services add-iam-policy-binding pipeline-api --region="$REGION" \
  --member="serviceAccount:${ADMIN_SA}" --role=roles/run.invoker -q >/dev/null

echo "--- deploy jobs (same image, module entrypoints)"
for job in "${JOBS[@]}"; do
  module="app.jobs.${job//-/_}"
  # Jobs that post from inside the job (generate-short) must NOT retry — a crash
  # mid-publish would double-post. collect/seed are idempotent; generate-report
  # resumes via a Firestore lease, so retrying is safe (docs 10 §6.3).
  retries=0
  [[ "$job" == "collect" || "$job" == "seed" || "$job" == "generate-report" ]] && retries=1
  # The Research Agent run is long, memory-heavier, and (M2) fans work out onto
  # threads — up to research_max_concurrency parallel LLM/fetch workers — so it
  # gets 2 CPUs and 2Gi where the daily jobs stay at 1/512Mi.
  memory=512Mi
  cpu=1
  timeout=1800
  [[ "$job" == "generate-report" ]] && { memory=2Gi; cpu=2; timeout=3600; }
  gcloud run jobs deploy "job-${job}" \
    --image="$IMAGE" --region="$REGION" \
    --service-account="$PIPELINE_SA" \
    --memory="$memory" --cpu="$cpu" --max-retries="$retries" --task-timeout="$timeout" \
    --set-env-vars="$COMMON_ENV" \
    --set-secrets="$SECRET_ENV" \
    --command=python --args=-m,"$module"
  # pipeline-api (as pipeline-sa) triggers these jobs for the admin "Run now" button
  gcloud run jobs add-iam-policy-binding "job-${job}" --region="$REGION" \
    --member="serviceAccount:${PIPELINE_SA}" --role=roles/run.invoker -q >/dev/null
done

echo "pipeline deployed. Seed once with:"
echo "  gcloud run jobs execute job-seed --region $REGION --wait"
echo "Then: ./11-deploy-admin.sh"
