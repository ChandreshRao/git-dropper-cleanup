# Manual demo runbook

Repeatable demo against the **`test-affected-repo`** GitHub demo. First-time branch seeding: [SETUP.md](SETUP.md) (not part of this loop).

**Safety:** Do not open the infected clone in an editor or run `npm` / `vite` until `--check` is clean.

## Prerequisites

- `git-dropper-cleanup` installed: `uv sync --extra dev` from repo root.
- `.env` with **`CLONE_ROOT`** set (copy from `.env.example`). The tool clones URLs under `CLONE_ROOT/<owner>/test-affected-repo`.
- Demo repo on GitHub with seed tags from setup (see [SETUP.md](SETUP.md)).

Replace `<owner>` with your GitHub user or org.

### Variables

**Git Bash**

```bash
cd /c/repos/git-dropper-cleanup   # your checkout

export REPO_URL="https://github.com/<owner>/test-affected-repo.git"
export DEMO_REPO="$CLONE_ROOT/<owner>/test-affected-repo"
# Example if CLONE_ROOT=./clones in .env:
# export DEMO_REPO="/c/repos/git-dropper-cleanup/clones/<owner>/test-affected-repo"
```

**PowerShell**

```powershell
cd C:\repos\git-dropper-cleanup   # your checkout

$env:REPO_URL = "https://github.com/<owner>/test-affected-repo.git"
$env:DEMO_REPO = "C:\repos\git-dropper-cleanup\clones\<owner>\test-affected-repo"
# Match CLONE_ROOT in .env (relative paths resolve from the tool repo root).
```

**Notes**

- **Cleanup** (`uv run git-dropper-cleanup …`) works in Git Bash or PowerShell. Pass the URL as an argument **or** set `REPO_URL` / `DEMO_REPO` and run with no path (e.g. `uv run git-dropper-cleanup --check`).
- In **PowerShell**, use `$env:REPO_URL`, not `"$REPO_URL"` (that shell variable is usually empty).
- **Infect / reset** use bash scripts. On Windows, run them via Git Bash, or from PowerShell with `bash` on `PATH` (Git for Windows).

## Demo loop

### 1. Affect branches

Local clone required (`DEMO_REPO` must exist and have `origin`).

**Git Bash**

```bash
cd /c/repos/git-dropper-cleanup
bash demo/manual/infect-for-demo.sh
```

**PowerShell**

```powershell
cd C:\repos\git-dropper-cleanup
# DEMO_REPO must be set (see above). Uses Git Bash if `bash` is on PATH:
bash demo/manual/infect-for-demo.sh

# Or call bash explicitly:
& "C:\Program Files\Git\bin\bash.exe" demo/manual/infect-for-demo.sh
```

This resets only `affected/feature-a` and `affected/feature-b` to their clean seed tags, adds infected commits (`global.o = "x"` in `app.js`), and force-pushes to `origin`. Author and committer dates are copied from existing branch history—not the current clock.

**Not modified:** `main`, `unaffected/docs`.

### 2. Cleanup

Pass the **git URL**; the tool uses or creates the clone under `CLONE_ROOT`.

A fresh URL clone only has a local `main`; other branches show under `remotes/origin/…` in `--check`. A full `--rewrite` creates matching local branches from those remotes only after it finds infected commits and the worktree is clean. `--rewrite --branch NAME` creates that one branch when it exists only on `origin`, and leaves the other remote branches as remote-tracking refs. You can also work against your full local clone path if you prefer (`$DEMO_REPO` / `$env:DEMO_REPO`).

Markdown reports are written under `git-dropper-cleanup/reports/<owner>-test-affected-repo/`. Open the latest `check-*.md` for tabular branch and commit detail.

**Git Bash — check**

```bash
uv run git-dropper-cleanup "$REPO_URL" --check
# Or, after export REPO_URL:
uv run git-dropper-cleanup --check
```

**PowerShell — check**

```powershell
uv run git-dropper-cleanup $env:REPO_URL --check
# Or, after $env:REPO_URL = "...":
uv run git-dropper-cleanup --check
```

You can always pass the URL literally (no variable):

```powershell
uv run git-dropper-cleanup "https://github.com/<owner>/test-affected-repo.git" --check
```

Expect exit code **1** and output similar to:

- `main`: clean
- `unaffected/docs`: clean
- `affected/feature-a`: N affected commits
- `affected/feature-b`: N affected commits
- `origin/affected/feature-a` (and `-b`): affected
- Listed commit SHAs with `app.js`

**Single-branch rewrite**

Git Bash:

```bash
uv run git-dropper-cleanup "$REPO_URL" --rewrite --branch affected/feature-a
uv run git-dropper-cleanup "$REPO_URL" --push --branch affected/feature-a
```

PowerShell:

```powershell
uv run git-dropper-cleanup $env:REPO_URL --rewrite --branch affected/feature-a
uv run git-dropper-cleanup $env:REPO_URL --push --branch affected/feature-a
```

**Full clone rewrite**

Git Bash:

```bash
uv run git-dropper-cleanup "$REPO_URL" --rewrite
uv run git-dropper-cleanup "$REPO_URL" --push --branch affected/feature-a
uv run git-dropper-cleanup "$REPO_URL" --push --branch affected/feature-b
```

PowerShell:

```powershell
uv run git-dropper-cleanup $env:REPO_URL --rewrite
uv run git-dropper-cleanup $env:REPO_URL --push --branch affected/feature-a
uv run git-dropper-cleanup $env:REPO_URL --push --branch affected/feature-b
```

If you rewrite `main` or `master`, add `--push-main`. Demo setup keeps `main` clean, so you usually only push the affected branches.

### 3. Verify

**Git Bash**

```bash
uv run git-dropper-cleanup "$REPO_URL" --check
git -C "$DEMO_REPO" show affected/feature-a:app.js | head
```

**PowerShell**

```powershell
uv run git-dropper-cleanup $env:REPO_URL --check
git -C $env:DEMO_REPO show affected/feature-a:app.js | Select-Object -First 10
```

Expect exit code **0**: worktree clean; affected branches clean after rewrite; `main` and `unaffected/docs` still clean. `app.js` should not contain `global.o`.

## Before the next demo

Run step 1 again, then repeat steps 2–3.

## Reset to clean (no infection)

**Git Bash**

```bash
bash demo/manual/reset-branches.sh
```

**PowerShell**

```powershell
bash demo/manual/reset-branches.sh
# Or: & "C:\Program Files\Git\bin\bash.exe" demo/manual/reset-branches.sh
```

Resets `affected/feature-a` and `affected/feature-b` to their `demo/seed/*` tags and force-pushes to `origin`. Does not touch `main` or `unaffected/docs`.

## Signing

The demo repo has local signing disabled. Rewrites produce unsigned commits; that is supported. See [docs/signing.md](../../docs/signing.md) if you later want Verified history.
