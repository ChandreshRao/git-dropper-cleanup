"""Push rewritten refs with --force-with-lease.

main and master are not force-pushed unless --push-main is set.
Backup refs under refs/backup/git-dropper-cleanup are never pushed.
"""

from __future__ import annotations

from git_dropper_cleanup.gitio import Git, command_failure, for_each_ref, local_branches
from git_dropper_cleanup.md_report import PushOutcome, write_push_report

PROTECTED_BRANCHES = {"main", "master"}


def push_one(git: Git, label: str, *args: str) -> tuple[bool, str]:
    """Push one ref. Return success and detail when the push fails."""
    print(f"Pushing {label}")
    result = git.run(*args, check=False)
    if result.returncode == 0:
        return True, ""
    detail = command_failure(result.returncode, result.stderr, result.stdout)
    print(f"Push failed for {label}: {detail}")
    return False, detail


def remote_sha(git: Git, ref: str) -> str | None:
    """Return the origin oid of ref, '' when it is absent, or None when the lookup fails."""
    result = git.run("ls-remote", "origin", ref, check=False)
    if result.returncode != 0:
        detail = command_failure(result.returncode, result.stderr, result.stdout)
        print(f"Could not read origin {ref}: {detail}")
        return None
    for line in result.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if name == ref and sha:
            return sha
    return ""


def was_rewritten(git: Git) -> bool:
    """Return whether a local backup namespace exists from a history rewrite."""
    for namespace in ("refs/original", "refs/backup/git-dropper-cleanup", "refs/backup/strip-dropper"):
        if for_each_ref(git, namespace):
            return True
    return False


def push_repo(
    git: Git,
    push_main: bool,
    rewritten: bool,
    only_branch: str | None = None,
    *,
    write_report: bool = True,
) -> int:
    """Push local branches, or only one branch. Rewritten tags are pushed only for a full rewrite.

    A rewritten main or master requires --push-main. No refs are pushed when that flag is missing.
    """
    outcomes: list[PushOutcome] = []
    refused: str | None = None
    exit_code = 0

    def finish() -> int:
        if write_report:
            path = write_push_report(
                repo=str(git.repo),
                rewritten=rewritten,
                only_branch=only_branch,
                push_main=push_main,
                outcomes=outcomes,
                refused=refused,
                exit_code=exit_code,
            )
            print(f"Report written: {path}")
        return exit_code

    if only_branch:
        ref = f"refs/heads/{only_branch}"
        exists = git.run("show-ref", "--verify", "--quiet", ref, check=False)
        if exists.returncode != 0:
            raise SystemExit(f"No local branch named {only_branch}.")
        branches = [only_branch]
    else:
        branches = local_branches(git)
    protected = [name for name in branches if name in PROTECTED_BRANCHES]
    if rewritten and protected and not push_main:
        names = ", ".join(protected)
        refused = f"Refusing to force-push {names} without --push-main. No branches were pushed."
        exit_code = 1
        print(refused)
        return finish()
    if not branches:
        print("No local branches to push.")
        return finish()
    lease = ["--force-with-lease"] if rewritten else []
    failed: list[str] = []
    for branch in branches:
        ok, detail = push_one(git, branch, "push", *lease, "origin", f"refs/heads/{branch}:refs/heads/{branch}")
        if ok:
            outcomes.append(PushOutcome(branch, "branch", "pushed", ""))
        else:
            outcomes.append(PushOutcome(branch, "branch", "failed", detail))
            failed.append(branch)
    if rewritten and not only_branch:
        tags = git.run("tag", "--list", check=False)
        for tag in [line for line in tags.stdout.splitlines() if line]:
            label = f"tag {tag}"
            ref = f"refs/tags/{tag}"
            remote = remote_sha(git, ref)
            if remote is None:
                outcomes.append(PushOutcome(tag, "tag", "failed", "could not read origin"))
                failed.append(label)
                continue
            if remote == "":
                ok, detail = push_one(git, label, "push", "origin", ref)
            else:
                local = git.run("rev-parse", ref).stdout.strip()
                if local == remote:
                    print(f"{label} already matches origin")
                    outcomes.append(PushOutcome(tag, "tag", "already matches origin", ""))
                    continue
                ok, detail = push_one(git, label, "push", f"--force-with-lease={ref}:{remote}", "origin", ref)
            if ok:
                outcomes.append(PushOutcome(tag, "tag", "pushed", ""))
            else:
                outcomes.append(PushOutcome(tag, "tag", "failed", detail))
                failed.append(label)
    if failed:
        print(f"These refs were not pushed: {', '.join(failed)}")
        exit_code = 1
    return finish()
