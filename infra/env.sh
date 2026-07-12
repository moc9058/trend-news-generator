#!/usr/bin/env bash
# Shared configuration sourced by every infra script.
export PROJECT_ID="${PROJECT_ID:-trend-news-generator}"
export REGION="${REGION:-asia-northeast1}"
export ADMIN_EMAIL="${ADMIN_EMAIL:-moc9058@gmail.com}"

export BUCKET="${PROJECT_ID}-media"
export AR_REPO="pipeline"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/pipeline:latest"

export PIPELINE_SA="pipeline-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export ADMIN_SA="admin-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export SCHEDULER_SA="scheduler-sa@${PROJECT_ID}.iam.gserviceaccount.com"

export JOBS=(collect generate-daily generate-weekly generate-monthly cleanup-drafts refresh-threads-token seed)
