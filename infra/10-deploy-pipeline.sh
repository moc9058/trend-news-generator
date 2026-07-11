#!/usr/bin/env bash
# Build the single pipeline image, deploy pipeline-api (service) + 6 jobs.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

echo "--- build image via Cloud Build"
gcloud builds submit ../pipeline --tag "$IMAGE" --region="$REGION"

SECRET_ENV="OPENAI_API_KEY=openai-api-key:latest"
SECRET_ENV+=",GEMINI_API_KEY=gemini-api-key:latest"
SECRET_ENV+=",X_CREDENTIALS=x-credentials:latest"
SECRET_ENV+=",THREADS_ACCESS_TOKEN=threads-access-token:latest"
SECRET_ENV+=",THREADS_USER_ID=threads-user-id:latest"
SECRET_ENV+=",NOTION_API_KEY=notion-api-key:latest"
if gcloud secrets describe ieee-api-key >/dev/null 2>&1; then
  SECRET_ENV+=",IEEE_API_KEY=ieee-api-key:latest"
fi

COMMON_ENV="PROJECT_ID=${PROJECT_ID},REGION=${REGION},GCS_BUCKET=${BUCKET},PIPELINE_SERVICE_ACCOUNT=${PIPELINE_SA}"

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
  # --max-retries=0 on publishing jobs prevents double posts on crash
  retries=0
  [[ "$job" == "collect" || "$job" == "seed" ]] && retries=1
  gcloud run jobs deploy "job-${job}" \
    --image="$IMAGE" --region="$REGION" \
    --service-account="$PIPELINE_SA" \
    --memory=512Mi --cpu=1 --max-retries="$retries" --task-timeout=1800 \
    --set-env-vars="$COMMON_ENV" \
    --set-secrets="$SECRET_ENV" \
    --command=python --args=-m,"$module"
done

echo "pipeline deployed. Seed once with:"
echo "  gcloud run jobs execute job-seed --region $REGION --wait"
echo "Then: ./11-deploy-admin.sh"
