#!/bin/bash
# Push updated calls (data/notes.json etc.). The GitHub job rebuilds and deploys the page on push.
# Refuses to publish if the self-check finds a call that breaks the rules.
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 render.py --strict >/dev/null; then
  echo "Self-check failed; fix data/notes.json first:"
  cat site/lint.json
  exit 2
fi

git add data/notes.json config.json RUNBOOK.md README.md ./*.py .github .gitignore 2>/dev/null || true
[ -f data/backfill.json ] && git add data/backfill.json
if git diff --cached --quiet; then
  echo "No call changes to push. Numbers refresh on their own every 30 minutes."
  exit 0
fi
git commit --quiet -m "calls: update $(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M IST')"
git checkout -- data/results.json 2>/dev/null || true   # the GitHub job owns this file
git pull --rebase --quiet
git push --quiet
echo "Pushed $(git rev-parse --short HEAD). The page rebuilds in about a minute."
