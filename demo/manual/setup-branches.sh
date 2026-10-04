#!/usr/bin/env bash
# One-time: seed demo branches with clean history (no infection). See SETUP.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Git Bash on Windows: /c/repos/test-affected-repo
DEMO_REPO="${DEMO_REPO:-/c/repos/test-affected-repo}"

BR_UNAFFECTED="unaffected/docs"
BR_AFFECTED_A="affected/feature-a"
BR_AFFECTED_B="affected/feature-b"
TAG_SEED_A="demo/seed/affected-feature-a"
TAG_SEED_B="demo/seed/affected-feature-b"

die() {
  echo "setup-branches: $*" >&2
  exit 1
}

git_repo() {
  git -C "$DEMO_REPO" "$@"
}

require_repo() {
  [[ -d "$DEMO_REPO/.git" ]] || die "not a git repo: $DEMO_REPO"
  git_repo remote get-url origin &>/dev/null || die "origin remote required"
}

already_seeded() {
  git_repo rev-parse "$TAG_SEED_A" &>/dev/null && return 0
  return 1
}

disable_signing_local() {
  git_repo config commit.gpgsign false
  git_repo config --unset-all user.signingkey 2>/dev/null || true
  git_repo config core.autocrlf false
  if ! git_repo config user.email &>/dev/null; then
    git_repo config user.email "demo@test-affected-repo.local"
  fi
  if ! git_repo config user.name &>/dev/null; then
    git_repo config user.name "Demo Operator"
  fi
}

write_app_js() {
  printf '%s' "$1" > "$DEMO_REPO/app.js"
}

commit_all() {
  local msg="$1"
  git_repo add -A
  git_repo diff --cached --quiet && die "nothing to commit for: $msg"
  git_repo commit -m "$msg"
}

ensure_on_main() {
  git_repo checkout main
}

seed_main_history() {
  ensure_on_main
  write_app_js $'export const version = 1;\n'
  commit_all "demo: add app.js bootstrap"

  write_app_js $'export const version = 1;\nexport function greet() {\n  return "hello";\n}\n'
  commit_all "demo: add greet helper"

  printf '%s\n' "# Demo repo" "Manual git-dropper-cleanup demos." > "$DEMO_REPO/readme.txt"
  commit_all "demo: expand readme"

  mkdir -p "$DEMO_REPO/src"
  printf '%s' "export const API_BASE = '/api';\n" > "$DEMO_REPO/src/config.js"
  commit_all "demo: add src/config.js"

  printf '%s' "export function formatDate(d) {\n  return d.toISOString();\n}\n" > "$DEMO_REPO/src/format.js"
  commit_all "demo: add src/format.js"

  write_app_js $'export const version = 2;\nexport function greet() {\n  return "hello";\n}\nexport { API_BASE } from "./src/config.js";\n'
  commit_all "demo: wire config into app"

  printf '%s\n' "node_modules/" ".env" > "$DEMO_REPO/.gitignore"
  commit_all "demo: add gitignore"

  printf '%s\n' '{"name":"test-affected-repo","private":true}' > "$DEMO_REPO/package.json"
  commit_all "demo: add package.json"
}

seed_unaffected_docs() {
  git_repo checkout -B "$BR_UNAFFECTED"
  mkdir -p "$DEMO_REPO/docs"
  printf '%s\n' "# Docs" "Clean control branch for demos." > "$DEMO_REPO/docs/overview.md"
  commit_all "demo: docs overview"

  printf '%s\n' "## Runbook" "See git-dropper-cleanup demo/manual/RUNBOOK.md." >> "$DEMO_REPO/docs/overview.md"
  commit_all "demo: docs runbook link"

  printf '%s\n' "# Contributing" "Demo only — no npm install required." > "$DEMO_REPO/docs/contributing.md"
  commit_all "demo: contributing doc"
}

seed_affected_branch() {
  local branch="$1"
  local tag="$2"
  local prefix="$3"
  local run_fn="$4"

  git_repo checkout -B "$branch" main
  write_app_js $'export const version = 2;\nexport function greet() {\n  return "hello";\n}\nexport { API_BASE } from "./src/config.js";\n'
  printf '%s\n' "// $prefix feature module" > "$DEMO_REPO/src/${prefix}.js"
  commit_all "demo: $prefix scaffold"

  printf '%s' "export function ${run_fn}() {\n  return '${prefix}-ok';\n}\n" >> "$DEMO_REPO/src/${prefix}.js"
  commit_all "demo: $prefix logic"

  write_app_js $'export const version = 3;\nexport function greet() {\n  return "hello";\n}\nexport { API_BASE } from "./src/config.js";\n'
  commit_all "demo: $prefix bump app version"

  git_repo tag -f "$tag"
  echo "  tagged $tag at $(git_repo rev-parse --short HEAD)"
}

verify_no_infection() {
  # Setup must never write dropper markers; infection is infect-for-demo.sh only.
  local hits
  hits="$(git_repo grep -l -E "global\\.o\\s*=" -- main "$BR_UNAFFECTED" "$BR_AFFECTED_A" "$BR_AFFECTED_B" 2>/dev/null || true)"
  if [[ -n "$hits" ]]; then
    die "setup found dropper markers (setup must stay clean): $hits"
  fi
}

push_all() {
  git_repo push origin main
  git_repo push origin "$BR_UNAFFECTED"
  git_repo push origin "$BR_AFFECTED_A"
  git_repo push origin "$BR_AFFECTED_B"
  git_repo push origin "$TAG_SEED_A" "$TAG_SEED_B"
}

main() {
  require_repo
  if already_seeded; then
    echo "setup-branches: seed tags already exist (e.g. $TAG_SEED_A)."
    echo "Branches are ready. To rebuild, delete demo/seed/* tags and re-run — see SETUP.md."
    exit 0
  fi

  disable_signing_local
  echo "== Seeding clean history on main ($DEMO_REPO)"
  seed_main_history

  echo "== Branch $BR_UNAFFECTED"
  seed_unaffected_docs

  echo "== Branch $BR_AFFECTED_A"
  seed_affected_branch "$BR_AFFECTED_A" "$TAG_SEED_A" "featureA" "runFeatureA"

  echo "== Branch $BR_AFFECTED_B"
  seed_affected_branch "$BR_AFFECTED_B" "$TAG_SEED_B" "featureB" "runFeatureB"

  git_repo checkout main
  verify_no_infection
  echo "== Pushing to origin"
  push_all

  echo ""
  echo "Setup complete. Branches are clean (no infection)."
  echo "Next: bash demo/manual/infect-for-demo.sh before each demo (see RUNBOOK.md)."
  echo "Tool root: $TOOL_ROOT"
}

main "$@"
