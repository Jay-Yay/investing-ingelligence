#!/usr/bin/env bash
# pull -> run an `investor_intel` subcommand -> commit + push whatever landed in vault/data.
#
# Exists so nobody has to remember the "pull the data branch before collect/analyze/
# web-research/run-daily, then push afterwards" discipline documented in
# vault/00_System/Runbook.md - forgetting either half is exactly what produces duplicate
# scrapes or same-day signal-log conflicts across machines.
#
# Usage: scripts/sync-run.sh <investor_intel subcommand> [args...]
# Examples:
#   scripts/sync-run.sh run-daily
#   scripts/sync-run.sh collect --backfill 30
#   scripts/sync-run.sh analyze
#   scripts/sync-run.sh web-research
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <investor_intel subcommand> [args...]" >&2
  echo "example: $0 run-daily" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Resolve the `data`-branch worktree path dynamically (each machine may have it checked out
# somewhere different) instead of hardcoding a sibling directory name.
DATA_WORKTREE="$(
  git -C "$REPO_ROOT" worktree list --porcelain \
    | awk -v RS= '/branch refs\/heads\/data$/{print}' \
    | sed -n 's/^worktree //p' \
    | head -1
)"

if [[ -z "$DATA_WORKTREE" ]]; then
  echo "error: no worktree checked out on the 'data' branch." >&2
  echo "  set one up once with: git worktree add ../$(basename "$REPO_ROOT")-data data" >&2
  exit 1
fi

echo "==> [1/3] pulling data branch ($DATA_WORKTREE)"
if ! git -C "$DATA_WORKTREE" pull --ff-only origin data; then
  cat >&2 <<EOF
error: 'data' branch has diverged from origin/data - refusing to guess how to merge.
This usually means another machine pushed a different same-day judgment (e.g. the
portfolio monitor's signal log) that needs a human to pick, not an auto-merge.
Resolve manually, then re-run:
  cd $DATA_WORKTREE && git status
EOF
  exit 1
fi

echo "==> [2/3] running: uv run python -m investor_intel $*"
set +e
(cd "$REPO_ROOT" && uv run python -m investor_intel "$@")
RUN_EXIT=$?
set -e

echo "==> [3/3] committing + pushing whatever landed in vault/ (even on failure - partial progress is still worth keeping, matching daily-collect.yml's policy)"
cd "$DATA_WORKTREE"
git add -A
if git diff --cached --quiet; then
  echo "==> nothing changed, nothing to sync"
else
  git commit -m "sync: $* ($(date -u +%Y-%m-%dT%H:%M:%SZ) UTC, $(hostname -s))"
  git -c http.postBuffer=524288000 push origin HEAD:data
fi

if [[ "$RUN_EXIT" -ne 0 ]]; then
  echo "==> note: 'investor_intel $*' exited $RUN_EXIT (synced anyway; see output above)" >&2
fi
exit "$RUN_EXIT"
