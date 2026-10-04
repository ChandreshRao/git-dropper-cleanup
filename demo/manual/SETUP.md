# One-time demo repo setup

Creates **branches and clean commit history only**. It does **not** infect anything (no `global.o` / dropper markers). Infection is always [infect-for-demo.sh](infect-for-demo.sh) before a demo.

Use this **once** (or when rebuilding the demo clone). The live demo loop is in [RUNBOOK.md](RUNBOOK.md).

## Target repository

Default path: `C:\repos\test-affected-repo` (Git Bash: `/c/repos/test-affected-repo`).

Override:

```bash
export DEMO_REPO=/c/repos/test-affected-repo
```

Requirements:

- Git clone with **`origin`** configured (e.g. `https://github.com/<owner>/test-affected-repo.git`).
- Run scripts from **Git Bash** on Windows (same as other bash scripts in this project).

## What setup creates

| Ref | Purpose |
| --- | --- |
| `main` | ~8 clean commits (app.js, src/, docs files) |
| `unaffected/docs` | Clean control branch; infect script never touches it |
| `affected/feature-a` | Clean feature history; infected only by `infect-for-demo.sh` |
| `affected/feature-b` | Separate clean feature history |
| `demo/seed/affected-feature-a` | Tag at last **clean** commit on feature-a |
| `demo/seed/affected-feature-b` | Tag at last **clean** commit on feature-b |

Existing branches such as `feat/change_1` are not modified.

**No dropper markers** are added during setup. Infection is only for demos (`infect-for-demo.sh`).

## Signing (this clone only)

Setup disables commit signing in the demo repo only:

- `commit.gpgsign = false`
- `user.signingkey` unset

Your global git signing settings are unchanged. Rewrites run unsigned, which is supported by git-dropper-cleanup.

## Run setup

From the **git-dropper-cleanup** repo root:

```bash
cd /c/repos/git-dropper-cleanup
bash demo/manual/setup-branches.sh
```

If seed tags already exist, the script exits without changing history.

## Rebuild from scratch

Only if you intentionally reset the demo repo:

1. Delete local seed tags: `git tag -d demo/seed/affected-feature-a demo/seed/affected-feature-b`
2. Delete the same tags on origin if present.
3. Reset or recreate branches as needed.
4. Run `setup-branches.sh` again.

## After setup

Before each presentation, run [infect-for-demo.sh](infect-for-demo.sh), then follow [RUNBOOK.md](RUNBOOK.md).
