#!/usr/bin/env bash
# Build and deploy the Next.js admin UI behind Cloud Run IAP.
# Fallback if --iap is unavailable on the account: see docs/runbook.md
# (NextAuth Google provider + email allowlist).
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

ADMIN_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/admin:latest"
PIPELINE_API_URL="$(gcloud run services describe pipeline-api --region "$REGION" --format='value(status.url)')"

echo "--- build admin image"
gcloud builds submit ../admin --tag "$ADMIN_IMAGE" --region="$REGION"

ADMIN_ENV="PROJECT_ID=${PROJECT_ID},PIPELINE_API_URL=${PIPELINE_API_URL},GCS_BUCKET=${BUCKET}"

# optional: the LLM trace card on the research run page reads back from LangSmith.
# Same switch as the pipeline (10-deploy-pipeline.sh) — the secret's existence.
# Delete the secret and redeploy and --clear-secrets drops the key, which is what
# langsmith.ts checks, so the card disappears along with the pipeline's tracing.
# The accessor grant lives here, next to the mount, NOT in 01-secrets.sh: that
# script is interactive and ./deploy.sh skips it by default, so a grant placed
# there never runs on a routine deploy and the revision fails to start.
SECRET_FLAG=(--clear-secrets)
if gcloud secrets describe langsmith-api-key >/dev/null 2>&1; then
  SECRET_FLAG=(--set-secrets="LANGSMITH_API_KEY=langsmith-api-key:latest")
  ADMIN_ENV+=",LANGSMITH_PROJECT=${PROJECT_ID}"
  gcloud secrets add-iam-policy-binding langsmith-api-key \
    --member="serviceAccount:${ADMIN_SA}" --role=roles/secretmanager.secretAccessor -q >/dev/null
fi

echo "--- deploy admin-ui with IAP"
gcloud beta run deploy admin-ui \
  --image="$ADMIN_IMAGE" --region="$REGION" \
  --service-account="$ADMIN_SA" \
  --iap \
  --memory=512Mi --cpu=1 --max-instances=2 \
  --set-env-vars="$ADMIN_ENV" \
  "${SECRET_FLAG[@]}"

echo "--- allow ${ADMIN_EMAIL} through IAP"
gcloud beta iap web add-iam-policy-binding \
  --member="user:${ADMIN_EMAIL}" \
  --role=roles/iap.httpsResourceAccessor \
  --region="$REGION" \
  --resource-type=cloud-run \
  --service=admin-ui

echo "admin-ui deployed. Next: ./20-schedulers.sh"
