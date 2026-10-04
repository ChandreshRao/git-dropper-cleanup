"""Read-only report of clean branches and commits that still contain the dropper.

Does not edit the worktree, move refs, or push.
"""

from __future__ import annotations

from git_dropper_cleanup.detect import GREP_PATTERN, clean_tree, is_code_path, rel
from git_dropper_cleanup.gitio import Git, current_branch, display_ref, for_each_ref, rev_list
from git_dropper_cleanup.md_report import commit_meta, write_check_report

BACKUP_NAMESPACES = (
    "refs/original",
    "refs/backup/git-dropper-cleanup",
    "refs/backup/strip-dropper",  # older tool name
)


def grep_commits(git: Git, commits: list[str]) -> list[str]:
    """Return commit:path lines whose blobs match the dropper. Does not print payload text."""
    hits: list[str] = []
    for start in range(0, len(commits), 20):
        chunk = commits[start : start + 20]
        result = git.run("grep", "-I", "-l", "-E", GREP_PATTERN, *chunk, check=False)
        if result.returncode == 0:
            hits.extend(line for line in result.stdout.splitlines() if line)
        elif result.returncode not in (0, 1):
            detail = (result.stderr or "").strip()
            raise SystemExit(f"git grep failed: {detail}")
    return hits


def infected_commits(git: Git, commits: list[str]) -> dict[str, list[str]]:
    """Map each infected commit SHA to its code-file paths. tasks.json is not included."""
    found: dict[str, list[str]] = {}
    for line in grep_commits(git, commits):
        sha, _, path = line.partition(":")
        if not sha or not is_code_path(path):
            continue
        paths = found.setdefault(sha, [])
        if path not in paths:
            paths.append(path)
    return found


def reachable(git: Git, ref: str) -> set[str]:
    """Return every commit reachable from ref."""
    return set(rev_list(git, ref))


def backup_hits(git: Git) -> list[str]:
    """Return dropper hits under backup namespaces. Those refs are not pushed."""
    commits: list[str] = []
    for namespace in BACKUP_NAMESPACES:
        listed = git.run("for-each-ref", "--format=%(objectname)", namespace, check=False)
        if listed.returncode != 0:
            continue
        commits.extend(line for line in listed.stdout.splitlines() if line)
    if not commits:
        return []
    return grep_commits(git, commits)


def _ref_groups(git: Git) -> tuple[list[str], list[str], list[str]]:
    """Return local branch refs, tag refs, and remote-tracking refs."""
    return (
        for_each_ref(git, "refs/heads"),
        for_each_ref(git, "refs/tags"),
        for_each_ref(git, "refs/remotes"),
    )


def _status_line(count: int) -> str:
    """Return the clean or affected wording for one ref."""
    if count == 0:
        return "clean"
    noun = "commit" if count == 1 else "commits"
    return f"{count} affected {noun}"


def _ref_table_rows(
    refs: list[str],
    infected: dict[str, list[str]],
    reach: dict[str, set[str]],
) -> tuple[list[list[str]], list[str]]:
    """Return table rows and clean ref display names."""
    rows: list[list[str]] = []
    clean: list[str] = []
    for ref in refs:
        count = sum(1 for sha in infected if sha in reach[ref])
        label = display_ref(ref)
        status = _status_line(count)
        rows.append([label, status, str(count)])
        if count == 0:
            clean.append(label)
    return rows, clean


def _print_ref_section(title: str, refs: list[str], infected: dict[str, list[str]], reach: dict[str, set[str]]) -> None:
    """Print one ref section, including refs that contain no dropper."""
    print(f"{title}:")
    if not refs:
        print("  none")
        return
    for ref in refs:
        count = sum(1 for sha in infected if sha in reach[ref])
        print(f"  {display_ref(ref)}: {_status_line(count)}")


def check_repo(git: Git, *, write_report: bool = True) -> int:
    """Print the worktree, every branch, and each affected commit once. Read-only."""
    code_hits, task_hits = clean_tree(git.repo, write=False)
    rel_code = [rel(git.repo, path) for path in code_hits]
    rel_tasks = [rel(git.repo, path) for path in task_hits]
    branches, tags, remotes = _ref_groups(git)
    all_refs = branches + tags + remotes
    reach = {ref: reachable(git, ref) for ref in all_refs}
    commits = rev_list(git, "--branches", "--tags", "--remotes")
    infected = infected_commits(git, commits)
    label = current_branch(git) or "detached HEAD"
    print(f"== {git.repo}")
    if code_hits:
        print(f"worktree ({label}):")
        for path in rel_code:
            print(f"  {path}")
    else:
        print(f"worktree ({label}): clean")
    for path in rel_tasks:
        print(f"tasks.json has a dropper marker and was not edited: {path}")
    _print_ref_section("branches", branches, infected, reach)
    _print_ref_section("tags", tags, infected, reach)
    _print_ref_section("remotes", remotes, infected, reach)
    commit_rows: list[list[str]] = []
    if infected:
        print("commits:")
        order = [sha for sha in commits if sha in infected]
        for sha in order:
            holders = [
                display_ref(ref)
                for ref in branches + tags
                if sha in reach[ref]
            ]
            if not holders:
                holders = [display_ref(ref) for ref in remotes if sha in reach[ref]]
            paths = ", ".join(infected[sha])
            print(f"  {sha[:12]}  {', '.join(holders)}  {paths}")
            meta = commit_meta(git, sha)
            commit_rows.append(
                [
                    sha[:12],
                    meta.author,
                    meta.committer,
                    meta.subject,
                    paths,
                    ", ".join(holders),
                ]
            )
    else:
        print("commits: none")
    backup_note: str | None = None
    if backup_hits(git):
        backup_note = (
            "refs/backup/git-dropper-cleanup (or older refs/backup/strip-dropper) "
            "or refs/original still has the dropper and is not pushed"
        )
        print(f"backup: {backup_note}")
    history_hit = bool(infected)
    exit_code = 1 if code_hits or task_hits or history_hit else 0
    if write_report:
        branch_rows, clean_branches = _ref_table_rows(branches, infected, reach)
        tag_rows, clean_tags = _ref_table_rows(tags, infected, reach)
        remote_rows, clean_remotes = _ref_table_rows(remotes, infected, reach)
        clean_refs = clean_branches + clean_tags + clean_remotes
        path = write_check_report(
            repo=str(git.repo),
            worktree_label=label,
            code_hits=rel_code,
            task_hits=rel_tasks,
            branch_rows=branch_rows,
            tag_rows=tag_rows,
            remote_rows=remote_rows,
            clean_refs=clean_refs,
            commit_rows=commit_rows,
            backup_note=backup_note,
            exit_code=exit_code,
        )
        print(f"Report written: {path}")
    return exit_code
