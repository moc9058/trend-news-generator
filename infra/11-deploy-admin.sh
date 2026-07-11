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

echo "--- deploy admin-ui with IAP"
gcloud beta run deploy admin-ui \
  --image="$ADMIN_IMAGE" --region="$REGION" \
  --service-account="$ADMIN_SA" \
  --iap \
  --memory=512Mi --cpu=1 --max-instances=2 \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},PIPELINE_API_URL=${PIPELINE_API_URL},GCS_BUCKET=${BUCKET}"

echo "--- allow ${ADMIN_EMAIL} through IAP"
gcloud beta iap web add-iam-policy-binding \
  --member="user:${ADMIN_EMAIL}" \
  --role=roles/iap.httpsResourceAccessor \
  --region="$REGION" \
  --resource-type=cloud-run \
  --service=admin-ui

echo "admin-ui deployed. Next: ./20-schedulers.sh"
