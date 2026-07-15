#!/usr/bin/env bash
# One-time project bootstrap: APIs, Firestore, GCS, Artifact Registry, SAs, IAM.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

gcloud config set project "$PROJECT_ID"

echo "--- enabling APIs"
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  iap.googleapis.com \
  iamcredentials.googleapis.com

echo "--- Firestore (Native mode)"
gcloud firestore databases create --location="$REGION" --type=firestore-native 2>/dev/null \
  || echo "firestore database already exists"

echo "--- Firestore composite indexes (async builds; duplicates are skipped)"
# Mirrors firestore.indexes.json (kept for `firebase deploy --only firestore:indexes`).
create_index() {
  gcloud firestore indexes composite create --collection-group="$1" --query-scope=COLLECTION \
    "${@:2}" --async 2>/dev/null || echo "index on $1 already exists"
}
create_index items \
  --field-config=field-path=categoryId,order=ascending \
  --field-config=field-path=collectedAt,order=descending
create_index items \
  --field-config=field-path=categoryId,order=ascending \
  --field-config=field-path=titleNormHash,order=ascending \
  --field-config=field-path=collectedAt,order=descending
create_index posts \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=createdAt,order=descending
create_index posts \
  --field-config=field-path=format,order=ascending \
  --field-config=field-path=createdAt,order=descending
create_index sources \
  --field-config=field-path=categoryId,order=ascending \
  --field-config=field-path=enabled,order=ascending
create_index researchRuns \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=createdAt,order=ascending
# chat: getChatThreads() = where(status==active) + orderBy(lastMessageAt desc).
# An equality filter plus an orderBy on a DIFFERENT field always needs a
# composite index — without it /chat 500s on every load, empty collection or not.
create_index chatThreads \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=lastMessageAt,order=descending

echo "--- GCS bucket (private)"
gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
  --uniform-bucket-level-access 2>/dev/null || echo "bucket already exists"

echo "--- Artifact Registry"
gcloud artifacts repositories create "$AR_REPO" --repository-format=docker \
  --location="$REGION" 2>/dev/null || echo "repo already exists"

echo "--- service accounts"
for sa in pipeline-sa admin-sa scheduler-sa; do
  gcloud iam service-accounts create "$sa" --display-name="$sa" 2>/dev/null \
    || echo "$sa already exists"
done

echo "--- IAM: pipeline-sa"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PIPELINE_SA}" --role=roles/datastore.user --condition=None -q >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${PIPELINE_SA}" --role=roles/storage.objectAdmin -q >/dev/null
# self token-creator: needed to mint V4 signed URLs from Cloud Run (no private key)
gcloud iam service-accounts add-iam-policy-binding "$PIPELINE_SA" \
  --member="serviceAccount:${PIPELINE_SA}" --role=roles/iam.serviceAccountTokenCreator -q >/dev/null

echo "--- IAM: admin-sa"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${ADMIN_SA}" --role=roles/datastore.user --condition=None -q >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${ADMIN_SA}" --role=roles/storage.objectViewer -q >/dev/null

echo "bootstrap done. Next: ./01-secrets.sh"
