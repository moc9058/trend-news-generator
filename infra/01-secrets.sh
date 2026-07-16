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

# This script only sets VALUES. The IAM that lets a service account read a secret
# lives next to the mount — pipeline-sa in 10-deploy-pipeline.sh, admin-sa (the
# LangSmith key it reads traces back with) in 11-deploy-admin.sh. Grants here
# would be invisible to a plain ./deploy.sh, which skips this interactive script.

echo "secrets done. Next: ./10-deploy-pipeline.sh"
