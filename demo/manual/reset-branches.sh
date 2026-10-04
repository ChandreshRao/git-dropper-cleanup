#!/usr/bin/env bash
# Reset affected demo branches to clean seed tags and push (removes infection).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEMO_REPO="${DEMO_REPO:-/c/repos/test-affected-repo}"

BR_AFFECTED_A="affected/feature-a"
BR_AFFECTED_B="affected/feature-b"
TAG_SEED_A="demo/seed/affected-feature-a"
TAG_SEED_B="demo/seed/affected-feature-b"

die() {
  echo "reset-branches: $*" >&2
  exit 1
}

git_repo() {
  git -C "$DEMO_REPO" "$@"
}

require_repo() {
  [[ -d "$DEMO_REPO/.git" ]] || die "not a git repo: $DEMO_REPO"
  git_repo remote get-url origin &>/dev/null || die "origin remote required"
  git_repo rev-parse "$TAG_SEED_A" &>/dev/null || die "missing $TAG_SEED_A — run setup-branches.sh (see SETUP.md)"
  git_repo rev-parse "$TAG_SEED_B" &>/dev/null || die "missing $TAG_SEED_B — run setup-branches.sh (see SETUP.md)"
}

reset_branch() {
  local branch="$1"
  local seed_tag="$2"

  echo "== $branch -> $seed_tag"
  git_repo checkout "$branch"
  git_repo reset --hard "$seed_tag"
  git_repo push --force-with-lease origin "$branch"
}

main() {
  require_repo
  reset_branch "$BR_AFFECTED_A" "$TAG_SEED_A"
  reset_branch "$BR_AFFECTED_B" "$TAG_SEED_B"
  git_repo checkout main

  echo ""
  echo "Affected branches reset to clean seeds and pushed to origin."
  echo "Untouched: main, unaffected/docs"
  echo ""
  echo "Verify: uv run git-dropper-cleanup \"$DEMO_REPO\" --check   (expect exit 0 for history)"
  echo "Re-infect before demo: bash demo/manual/infect-for-demo.sh"
  echo "Tool root: $TOOL_ROOT"
}

main "$@"
