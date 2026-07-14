#!/usr/bin/env bash
# commit.sh "<message>" [branch]
# Stage everything, commit with <message>, and push to origin/<branch> (default: master).
set -euo pipefail

msg="${1:-}"
branch="${2:-master}"

if [[ -z "$msg" ]]; then
  echo "usage: ./commit.sh \"<message>\" [branch]  (branch defaults to master)" >&2
  exit 1
fi

# Run from the repo root regardless of where the script is invoked.
cd "$(dirname "$0")"

git add .

# Nothing staged → don't fail the whole run.
if git diff --cached --quiet; then
  echo "nothing to commit — working tree clean"
  exit 0
fi

git commit -m "$msg"
git push origin "$branch"
