#!/usr/bin/env bash
# Interactive secret creation. Re-running adds new versions for changed values.
# Prerequisite: docs/setup-credentials.md walks through obtaining each value.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

create_or_update() {
  local name="$1" prompt="$2" optional="${3:-}"
  if [[ -n "$optional" ]]; then
    read -r -p "$prompt (empty to skip): " value
    [[ -z "$value" ]] && { echo "skipped $name"; return; }
  else
    read -r -p "$prompt: " value
    [[ -z "$value" ]] && { echo "ERROR: $name is required"; exit 1; }
  fi
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=-
  else
    printf '%s' "$value" | gcloud secrets create "$name" --replication-policy=automatic --data-file=-
  fi
}

create_or_update openai-api-key   "OpenAI API key (sk-...)"
create_or_update gemini-api-key   "Gemini API key (AI Studio)"
echo 'X credentials as one-line JSON: {"consumer_key":"...","consumer_secret":"...","access_token":"...","access_token_secret":"..."}'
create_or_update x-credentials    "X OAuth1.0a JSON"
create_or_update threads-access-token "Threads long-lived access token"
create_or_update threads-user-id  "Threads user ID (numeric)"
create_or_update notion-api-key   "Notion internal integration token (ntn_/secret_...)"
create_or_update ieee-api-key     "IEEE Xplore API key" optional
# Presence of this secret is what enables tracing in 10-deploy-pipeline.sh;
# deleting it and redeploying is the kill switch.
create_or_update langsmith-api-key "LangSmith API key (lsv2_...)" optional

echo "--- grant pipeline-sa access"
for s in openai-api-key gemini-api-key x-credentials threads-access-token threads-user-id notion-api-key ieee-api-key langsmith-api-key; do
  gcloud secrets describe "$s" >/dev/null 2>&1 || continue
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${PIPELINE_SA}" --role=roles/secretmanager.secretAccessor -q >/dev/null
done
# the refresh job rotates the threads token: needs versionAdder + version disable
gcloud secrets add-iam-policy-binding threads-access-token \
  --member="serviceAccount:${PIPELINE_SA}" --role=roles/secretmanager.secretVersionAdder -q >/dev/null
gcloud secrets add-iam-policy-binding threads-access-token \
  --member="serviceAccount:${PIPELINE_SA}" --role=roles/secretmanager.secretVersionManager -q >/dev/null

echo "secrets done. Next: ./10-deploy-pipeline.sh"
