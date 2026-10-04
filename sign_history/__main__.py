#!/usr/bin/env python3
"""Report commits GitHub would leave Unverified, then rewrite them if you ask.

A plain run only reads history. It prints every author or committer email that
is not the target email, and any commit that has no signature. It does not
edit the clone and it does not change git config.

--email and --name are optional. When omitted, the clone's user.email and
user.name are used. Pass --email when you want a specific GitHub noreply
(or other) address instead of whatever is in the clone config.

Pass --fix only after you decide those emails are not legitimate. --fix sets
both the author and committer to the target email and signs every commit.
The signing key must unlock without a passphrase.

Usage:
  uv run sign-history /path/to/clone
  uv run sign-history /path/to/clone --email you@users.noreply.github.com --name "You"
  uv run sign-history /path/to/clone --fix
  uv run sign-history /path/to/clone --fix --push --push-main
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}


def find_git() -> str:
    from shutil import which

    found = which("git")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    raise SystemExit("git was not found. Install Git and open a shell where git runs.")


GIT = find_git()


def git_exec(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, 6):
        result = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=env or {**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        detail = result.stderr or result.stdout or ""
        if result.returncode == 0 or "Could not resolve host" not in detail or attempt == 5:
            return result
        print(f"Could not resolve host (attempt {attempt}/5). Retrying.")
        time.sleep(2)
    assert result is not None
    return result


class Git:
    def __init__(self, repo: Path, hooks: Path):
        self.repo = repo
        self.hooks = hooks

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [GIT, "-c", f"core.hooksPath={self.hooks}", "-C", str(self.repo), *args]
        result = git_exec(cmd)
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise SystemExit(f"git {' '.join(args)} failed in {self.repo}: {detail}")
        return result

    def out(self, *args: str) -> str:
        return self.run(*args).stdout


def resolve_identity(git: Git, email: str | None, name: str | None) -> tuple[str, str]:
    """Return the author identity to enforce, from flags or the clone config."""
    if email is None:
        result = git.run("config", "--get", "user.email", check=False)
        email = result.stdout.strip() if result.returncode == 0 else ""
    if name is None:
        result = git.run("config", "--get", "user.name", check=False)
        name = result.stdout.strip() if result.returncode == 0 else ""
    if not email:
        raise SystemExit(
            "Pass --email with your GitHub noreply address, or set user.email in the clone."
        )
    if not name:
        name = email.split("@", 1)[0]
    return email, name


def signing_key(git: Git) -> Path:
    result = git.run("config", "--get", "user.signingkey", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit("No user.signingkey is configured. This script will not run git config.")
    key = result.stdout.strip()
    if key.startswith("ssh-"):
        raise SystemExit("user.signingkey is an inline key. Point it at the .pub file.")
    path = Path(os.path.expanduser(key))
    if not path.is_file():
        raise SystemExit(f"Signing key file is missing ({path}).")
    private = path.with_suffix("") if path.suffix == ".pub" else path
    if not private.is_file():
        raise SystemExit(f"Private key is missing ({private}).")
    return path


def require_clean(git: Git) -> None:
    status = git.out("status", "--porcelain")
    if not status.strip():
        return
    raise SystemExit(
        "Cannot rewrite: the worktree has uncommitted changes. Do not commit them.\n"
        f"Restore the last commit, then run this script again:\n"
        f"git -C {git.repo} restore ."
    )


def local_branches(git: Git) -> list[str]:
    text = git.out("for-each-ref", "--format=%(refname:short)", "refs/heads")
    return [line for line in text.splitlines() if line]


def history(git: Git) -> list[dict[str, str]]:
    text = git.out("log", "--branches", "--tags", "--format=%H%x09%h%x09%ae%x09%ce%x09%s")
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        full, short, author, committer, subject = line.split("\t", 4)
        rows.append(
            {
                "full": full,
                "short": short,
                "author": author,
                "committer": committer,
                "subject": subject,
            }
        )
    signed = signed_commits(git, [row["full"] for row in rows])
    for row in rows:
        row["signed"] = "yes" if row["full"] in signed else "no"
    return rows


def signed_commits(git: Git, shas: list[str]) -> set[str]:
    if not shas:
        return set()
    cmd = [GIT, "-c", f"core.hooksPath={git.hooks}", "-C", str(git.repo), "cat-file", "--batch"]
    result = subprocess.run(
        cmd,
        input="".join(f"{sha}\n" for sha in shas),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"git cat-file failed in {git.repo}: {detail}")
    found: set[str] = set()
    lines = result.stdout.splitlines()
    index = 0
    while index < len(lines):
        header = lines[index]
        index += 1
        parts = header.split()
        if len(parts) < 3 or parts[1] != "commit":
            continue
        sha, _, size_text = parts[0], parts[1], parts[2]
        try:
            size = int(size_text)
        except ValueError:
            continue
        body: list[str] = []
        consumed = 0
        while index < len(lines) and consumed < size:
            body.append(lines[index])
            consumed += len(lines[index].encode("utf-8", errors="replace")) + 1
            index += 1
        if index < len(lines) and lines[index] == "":
            index += 1
        header_lines = []
        for line in body:
            if line == "":
                break
            header_lines.append(line)
        if any(line.startswith("gpgsig ") for line in header_lines):
            found.add(sha)
    return found


def check_repo(git: Git, email: str, hint: bool = True) -> int:
    rows = history(git)
    print(f"== {git.repo}")
    print(f"account email: {email}")
    if not rows:
        print("no commits on branches or tags")
        return 0
    by_email: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    unsigned = []
    for row in rows:
        roles = []
        if row["author"] != email:
            roles.append("author")
        if row["committer"] != email:
            roles.append("committer")
        for role in roles:
            address = row["author"] if role == "author" else row["committer"]
            by_email[address].append((role, row))
        if row["signed"] == "no":
            unsigned.append(row)
    bad_commits = {row["full"] for pairs in by_email.values() for _, row in pairs}
    bad_commits.update(row["full"] for row in unsigned)
    print(f"commits GitHub can verify: {len(rows) - len(bad_commits)}")
    print(f"commits that can show Unverified: {len(bad_commits)}")
    if not by_email and not unsigned:
        print("emails: account email only, and every commit is signed")
        return 0
    if by_email:
        print("emails that are not the account email:")
        for address in sorted(by_email):
            pairs = by_email[address]
            author_count = sum(1 for role, _ in pairs if role == "author")
            committer_count = sum(1 for role, _ in pairs if role == "committer")
            print(f"  {address}")
            print(f"    author on {author_count} commits, committer on {committer_count} commits")
            seen: set[str] = set()
            for _, row in pairs:
                if row["full"] in seen:
                    continue
                seen.add(row["full"])
                print(f"    {row['short']} {row['subject']}")
    if unsigned:
        print("commits with no signature:")
        for row in unsigned:
            print(f"  {row['short']} author={row['author']} committer={row['committer']} {row['subject']}")
    if hint:
        print("Nothing was rewritten. Pass --fix to replace these emails and sign the commits.")
    return 1


def rewrite(git: Git, email: str, name: str) -> None:
    # The filter is shell code, so email and name only reach it as environment variables.
    env_filter = """
if [ "$GIT_AUTHOR_EMAIL" != "$SIGN_HISTORY_EMAIL" ]; then
  GIT_AUTHOR_EMAIL="$SIGN_HISTORY_EMAIL"
  GIT_AUTHOR_NAME="$SIGN_HISTORY_NAME"
fi
if [ "$GIT_COMMITTER_EMAIL" != "$SIGN_HISTORY_EMAIL" ]; then
  GIT_COMMITTER_EMAIL="$SIGN_HISTORY_EMAIL"
  GIT_COMMITTER_NAME="$SIGN_HISTORY_NAME"
fi
"""
    env = {
        **os.environ,
        "FILTER_BRANCH_SQUELCH_WARNING": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "SIGN_HISTORY_EMAIL": email,
        "SIGN_HISTORY_NAME": name,
    }
    cmd = [
        GIT,
        "-c",
        f"core.hooksPath={git.hooks}",
        "-C",
        str(git.repo),
        "filter-branch",
        "-f",
        "--env-filter",
        env_filter,
        "--commit-filter",
        'git commit-tree -S "$@"',
        "--tag-name-filter",
        "cat",
        "--",
        "--branches",
        "--tags",
    ]
    print(f"Rewriting {git.repo}")
    print(f"Email: {email}")
    print("Each commit will be signed. A passphrase prompt cannot be answered here.")
    result = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", env=env)
    if result.returncode != 0:
        raise SystemExit(f"Rewrite failed in {git.repo}")
    if check_repo(git, email, hint=False) != 0:
        raise SystemExit(f"Rewrite finished but {git.repo} can still show Unverified.")
    print("GitHub stays on the old commits until you pass --push --push-main.")


def push_repo(git: Git, push_main: bool) -> None:
    branches = local_branches(git)
    protected = [name for name in branches if name in PROTECTED_BRANCHES]
    if protected and not push_main:
        names = ", ".join(protected)
        raise SystemExit(f"Refusing to force-push {names} without --push-main. No branches were pushed.")
    for branch in branches:
        print(f"Pushing {branch}")
        git.run("push", "--force-with-lease", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
    tags = git.run("tag", "--list", check=False)
    for tag in [line for line in tags.stdout.splitlines() if line]:
        ref = f"refs/tags/{tag}"
        # Tags have no remote-tracking ref, so a bare --force-with-lease reports stale info.
        listed = git.run("ls-remote", "origin", ref)
        remote = ""
        for line in listed.stdout.splitlines():
            sha, _, name = line.partition("\t")
            if name == ref and sha:
                remote = sha
                break
        local = git.out("rev-parse", ref).strip()
        print(f"Pushing tag {tag}")
        if remote == "":
            git.run("push", "origin", ref)
        elif local != remote:
            git.run("push", f"--force-with-lease={ref}:{remote}", "origin", ref)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check which commit emails would show as Unverified. Rewrite only with --fix."
    )
    parser.add_argument("repo", type=Path, help="Path to a local clone")
    parser.add_argument(
        "--email",
        default=None,
        help="Email GitHub should treat as verified (default: user.email in the clone)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Name stored when an email is replaced (default: user.name in the clone)",
    )
    parser.add_argument("--fix", action="store_true", help="Replace other emails and sign every commit")
    parser.add_argument("--push", action="store_true", help="Force-push the rewritten branches with --force-with-lease")
    parser.add_argument("--push-main", action="store_true", help="Allow main or master to be force-pushed")
    args = parser.parse_args(argv)
    if args.push and not args.fix:
        parser.error("--push is only valid with --fix.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        raise SystemExit(f"{repo} is not a git clone")
    hooks = Path(tempfile.mkdtemp(prefix="sign-history-hooks-"))
    git = Git(repo, hooks)
    email, name = resolve_identity(git, args.email, args.name)
    if not args.fix:
        return check_repo(git, email)
    signing_key(git)
    require_clean(git)
    status = check_repo(git, email)
    if status == 0:
        print("No rewrite needed.")
        return 0
    rewrite(git, email, name)
    if args.push:
        push_repo(git, args.push_main)
    return 0


if __name__ == "__main__":
    sys.exit(main())
