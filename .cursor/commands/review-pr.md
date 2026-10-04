---
name: review-pr
description: Critical review of branch or PR changes against main for git-dropper-cleanup — bugs, security, repo invariants, tests, style. Use with /review-pr. Review-only; writes `.cursor/reviews/` only.
---

# git-dropper-cleanup — PR / branch review

**Review-only.** Do not edit application source. Write one file under `.cursor/reviews/` (gitignored). Find real flaws; skip filler.

## Token discipline

1. `git diff --stat origin/<base>...HEAD` (and `git status` if uncommitted work matters), then read **only changed hunks** and those functions plus direct callers. Use offset/limit on large files.
2. Do not read README, `docs/`, or unchanged modules unless a finding needs them.
3. Do not run tests or e2e unless the user asks. Name which verify command applies. Never run `--rewrite` or `--push` against a real clone/remote.
4. One row per issue, one-line text. No restating the diff. Omit empty sections (write `None`). **Positive Notes** max 3 bullets. Do not duplicate the same issue across sections.

## Scope (PR optional)

- Base defaults to **`main`** (user may override).
- `git fetch origin <base>` before diff; do not checkout/merge base. If fetch fails, note in Summary and use existing `origin/<base>` or local `<base>`.
- Diff: `git diff origin/<base>...HEAD`. Include working-tree changes when reviewing “current work.”
- With PR URL/number: prefer `gh pr view` / `gh pr diff` when `gh` exists; else same three-dot diff after fetch.
- Output: `.cursor/reviews/PR_<number|sanitized-branch>_REVIEW.md` (`/` → `-` in branch names).

## Instructions

1. Resolve scope; review **changed files only**.
2. Leave **Dev Notes** empty.
3. Apply **Hard invariants** (🔴), **Security**, and **Style** below.
4. Suggest improvements only when behavior and safety rules stay identical (simpler same logic, reuse existing helper). No new features, flags, or refactors outside the diff.

## Focus

Functional correctness · error handling · security · repo invariants · style/naming · tests for new/changed logic

## Hard invariants (🔴)

- Do not run code from the target clone (no node/npm/vite; no import/eval of repo files).
- Git in `src/` via `gitio.Git` / `git_exec` with empty `core.hooksPath`; flag raw `subprocess.run(["git", ...])` in `src/` (not tests).
- No `git config`; no signing keys in `.env` (only `CLONE_ROOT` in `env.py`).
- `tasks.json`: report only, never edit.
- Backup refs `refs/backup/git-dropper-cleanup/` never pushed; rewrite push uses `--force-with-lease`; `main`/`master` need `--push-main`.
- `--check` read-only; `require_clean` before rewrite/reset.
- Runtime stdlib only (`dependencies = []` in `pyproject.toml`); flag new deps.
- Flag `pyproject.toml` entry points / `git_dropper_cleanup.*` vs actual package layout (`src/`) or README command drift.

## Security

- `shell=True`; string-built argv; untrusted URL/branch/path as git args without `--` (injection, e.g. `-` prefix).
- Path escape from URL → `CLONE_ROOT`; symlinks; writes outside target repo.
- Secrets or credentialed URLs in logs/errors.
- Wrong encoding or corrupting binary blobs; temp paths not cleaned.
- Force-push or ref moves without backup when code path allows data loss.

## Style (this repo)

- **Config**: `.env` / `CLONE_ROOT` only in `src/env.py`; no scattered `os.getenv` for config (passing `os.environ` into subprocess is OK). Shared constants at module top.
- **Functions**: one job, short, early return; flag duplication of `gitio` helpers, unused params, speculative options, deep nesting.
- **Comments**: one-line docstring per new/changed function (what it returns + safety if relevant, like `gitio.py`). Flag noise, stale, or missing docstrings on new functions.
- `from __future__ import annotations`; failures → `SystemExit` with actionable message.

## Verify (name only; do not run destructive ops)

| When | Command |
| ---- | ------- |
| Unit | `uv run pytest` |
| E2e host | `bash e2e/run.sh` |
| E2e Docker | `docker build -f e2e/Dockerfile -t git-dropper-cleanup-e2e .` then `docker run --rm git-dropper-cleanup-e2e` |
| Smoke | `uv run git-dropper-cleanup --help` |

Severity: 🔴 must fix · 🟡 should fix · 🟢 minor

## Output template

```markdown
<details>
<summary>Agent feedback</summary>

# PR Review: [title or branch]

**PR**: #[n or branch] | **Base**: [base] | **Files**: [n] | **Lines**: +[a] / -[d]

## Summary

[1–2 sentences]

## Critical Issues

[Blocking list or None found]

<details><summary>Functional Concerns</summary>

| File | Line | Issue | Severity | Dev Notes |
| ---- | ---- | ----- | -------- | --------- |
| `src/foo.py` | 42 | One-line issue | 🔴 | |

</details>

<details><summary>Security</summary>

| File | Line | Issue | Severity | Dev Notes |
| ---- | ---- | ----- | -------- | --------- |

None — or rows as above.

</details>

<details><summary>Invariant Violations</summary>

| File | Line | Invariant | Severity | Dev Notes |
| ---- | ---- | --------- | -------- | --------- |

</details>

<details><summary>Style & Naming</summary>

| File | Line | Issue | Suggestion | Dev Notes |
| ---- | ---- | ----- | ---------- | --------- |

</details>

<details><summary>Unit Tests & Coverage</summary>

| Scope | Coverage | Notes | Dev Notes |
| ----- | -------- | ----- | --------- |

</details>

<details><summary>Positive Notes</summary>

- [max 3]

</details>

<details><summary>Recommendations</summary>

| Priority | Recommendation | Notes | Dev Notes |
| -------- | -------------- | ----- | --------- |

</details>

</details>
```

Invoke: `/review-pr`, optional PR URL/number, or “review branch against main.”
