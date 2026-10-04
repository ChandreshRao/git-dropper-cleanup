#!/usr/bin/env bash
# End-to-end: build an infected sample repo, rewrite it, verify clean.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SAMPLE="/tmp/git-dropper-cleanup-e2e-sample"
rm -rf "$SAMPLE"
mkdir -p "$SAMPLE"
cd "$SAMPLE"

git init -b main
git config user.email "e2e@example.com"
git config user.name "E2E"
git config commit.gpgsign false
git config core.autocrlf false
git config user.signingkey "$SAMPLE/missing.pub"

write_js() {
  printf '%s' "$1" > a.js
}

write_js $'ok\n'
git add a.js
git commit -m "clean root"

write_js $'ok\nglobal.o = "x"\n'
git add a.js
git commit -m "infected"

write_js $'changed\nglobal.o = "x"\n'
git add a.js
git commit -m "still infected"

echo "== check (expect failure)"
set +e
uv run git-dropper-cleanup "$SAMPLE" --check
CHECK_BEFORE=$?
set -e
if [[ "$CHECK_BEFORE" -eq 0 ]]; then
  echo "expected --check to fail before rewrite" >&2
  exit 1
fi

echo "== rewrite"
uv run git-dropper-cleanup "$SAMPLE" --rewrite

echo "== check (expect success)"
uv run git-dropper-cleanup "$SAMPLE" --check

if git show HEAD:a.js | grep -q 'global.o'; then
  echo "dropper still present in HEAD" >&2
  exit 1
fi

echo "e2e OK"
