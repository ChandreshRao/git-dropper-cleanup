#!/usr/bin/env bash
# Reset affected demo branches to clean seeds, add infection, push to origin.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DEMO_REPO="${DEMO_REPO:-/c/repos/test-affected-repo}"

BR_AFFECTED_A="affected/feature-a"
BR_AFFECTED_B="affected/feature-b"
TAG_SEED_A="demo/seed/affected-feature-a"
TAG_SEED_B="demo/seed/affected-feature-b"

AFFECTED_BRANCHES=("$BR_AFFECTED_A" "$BR_AFFECTED_B")

die() {
  echo "infect-for-demo: $*" >&2
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

disable_signing_local() {
  git_repo config commit.gpgsign false
  git_repo config --unset-all user.signingkey 2>/dev/null || true
}

write_app_js() {
  printf '%s' "$1" > "$DEMO_REPO/app.js"
}

commit_all() {
  local msg="$1"
  local author_date="${2:-}"
  local committer_date="${3:-$author_date}"
  git_repo add -A
  git_repo diff --cached --quiet && die "nothing to commit for: $msg"
  if [[ -n "$author_date" ]]; then
    GIT_AUTHOR_DATE="$author_date" GIT_COMMITTER_DATE="$committer_date" \
      git_repo commit -m "$msg" --date="$author_date"
  else
    git_repo commit -m "$msg"
  fi
}

read_commit_times() {
  # Sets HIST_AUTHOR and HIST_COMMITTER from an existing commit ref.
  local ref="$1"
  HIST_AUTHOR="$(git_repo log -1 --format=%aI "$ref")"
  HIST_COMMITTER="$(git_repo log -1 --format=%cI "$ref")"
  [[ -n "$HIST_AUTHOR" && -n "$HIST_COMMITTER" ]] || die "cannot read dates from $ref"
}

# Reuse timestamps from branch history (never "now" or synthetic offsets).
infect_commit_dates() {
  local seed_tag="$1"
  local seed_sha first_post_seed last_post_seed

  seed_sha="$(git_repo rev-parse "$seed_tag")"
  first_post_seed="$(git_repo rev-list --reverse "${seed_sha}..HEAD" 2>/dev/null | sed -n '1p')"
  last_post_seed="$(git_repo rev-parse HEAD 2>/dev/null || true)"

  if [[ -n "$first_post_seed" && "$last_post_seed" != "$seed_sha" ]]; then
    # Re-infect: keep the same author/committer times as the previous infected commits.
    read_commit_times "$first_post_seed"
    INFECT_A1="$HIST_AUTHOR"
    INFECT_C1="$HIST_COMMITTER"
    read_commit_times "$last_post_seed"
    INFECT_A2="$HIST_AUTHOR"
    INFECT_C2="$HIST_COMMITTER"
    return
  fi

  # First infect after setup: use the two clean feature commits on the seed lineage.
  read_commit_times "${seed_tag}^"
  INFECT_A1="$HIST_AUTHOR"
  INFECT_C1="$HIST_COMMITTER"
  read_commit_times "$seed_tag"
  INFECT_A2="$HIST_AUTHOR"
  INFECT_C2="$HIST_COMMITTER"
}

infect_branch() {
  local branch="$1"
  local seed_tag="$2"

  echo "== $branch (reset to $seed_tag)"
  git_repo checkout "$branch"
  infect_commit_dates "$seed_tag"
  git_repo reset --hard "$seed_tag"

  # Match e2e marker shape (see e2e/run.sh)
  write_app_js $'export const version = 3;\nexport function greet() {\n  return "hello";\n}\nexport { API_BASE } from "./src/config.js";\nglobal.o = "x"\n'
  commit_all "demo: infected commit" "$INFECT_A1" "$INFECT_C1"

  write_app_js $'export const version = 4;\nexport function greet() {\n  return "hello";\n}\nexport { API_BASE } from "./src/config.js";\nglobal.o = "x"\n'
  commit_all "demo: still infected" "$INFECT_A2" "$INFECT_C2"

  git_repo push --force-with-lease origin "$branch"
}

main() {
  require_repo
  disable_signing_local

  local b
  for b in "${AFFECTED_BRANCHES[@]}"; do
    case "$b" in
      "$BR_AFFECTED_A") infect_branch "$b" "$TAG_SEED_A" ;;
      "$BR_AFFECTED_B") infect_branch "$b" "$TAG_SEED_B" ;;
      *) die "internal: unknown branch $b" ;;
    esac
  done

  git_repo checkout main

  echo ""
  echo "Infection pushed for: ${AFFECTED_BRANCHES[*]}"
  echo "Untouched: main, unaffected/docs"
  echo ""
  echo "Next (from $TOOL_ROOT):"
  echo "  uv run git-dropper-cleanup \"$DEMO_REPO\" --check"
  echo "  uv run git-dropper-cleanup \"$DEMO_REPO\" --rewrite --branch $BR_AFFECTED_A"
  echo "  uv run git-dropper-cleanup \"$DEMO_REPO\" --push --branch $BR_AFFECTED_A"
  echo "  uv run git-dropper-cleanup \"$DEMO_REPO\" --check"
  echo ""
  echo "Full walkthrough: demo/manual/RUNBOOK.md"
}

main "$@"
