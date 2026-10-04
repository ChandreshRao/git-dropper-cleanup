"""Rewrite infected commits and their descendants without checking out each commit.

Clean ancestors keep their SHAs. A single-branch rewrite stops when another local
branch or tag still reaches the infected commits. This module does not push.
"""

from __future__ import annotations

from git_dropper_cleanup.detect import clean_tree, is_code_path, rel, strip_bytes
from git_dropper_cleanup.gitio import (
    Git,
    current_branch,
    display_ref,
    ensure_local_branches,
    for_each_ref,
    is_ancestor,
    local_branches,
    print_signing_help,
    require_clean,
    rev_list,
)
from git_dropper_cleanup.md_report import commit_meta, utc_now_iso, write_rewrite_report
from git_dropper_cleanup.report import infected_commits

COMMIT_MESSAGE = "Remove appended JavaScript dropper from branch tip."
BACKUP_PREFIX = "refs/backup/git-dropper-cleanup"


def fix_repo(git: Git) -> list:
    """Strip the dropper from the current checkout. Does not create a commit."""
    before, task_hits = clean_tree(git.repo, write=False)
    clean_tree(git.repo, write=True)
    for path in before:
        print(f"CLEANED {rel(git.repo, path)}")
    for path in task_hits:
        print(f"LEFT {rel(git.repo, path)} (tasks.json is only reported)")
    if not before and not task_hits:
        print(f"No dropper files in {git.repo}")
    return before


def commit_cleaned(git: Git, paths: list, sign: bool) -> None:
    """Commit staged dropper removals on the current branch. Requires a signing key."""
    if not paths:
        return
    for path in paths:
        git.run("add", "--", str(path))
    status = git.run("diff", "--cached", "--quiet", check=False)
    if status.returncode == 0:
        return
    cmd = ["commit"]
    if sign:
        cmd.append("-S")
    cmd.extend(["-m", COMMIT_MESSAGE, "--", *(str(path) for path in paths)])
    git.run(*cmd)
    print(f"Committed on {current_branch(git) or 'HEAD'}")


def branches_repo(git: Git, sign: bool) -> None:
    """Clean each local branch tip and commit when a signing key is configured.

    Without a signing key, only the current checkout is cleaned and no branch is switched.
    """
    if not sign:
        print("No signing key. Cleaning the current checkout only. Branches were not switched.")
        print_signing_help()
        fix_repo(git)
        return
    require_clean(git)
    start = current_branch(git)
    ensure_local_branches(git)
    for branch in local_branches(git):
        git.run("switch", branch)
        paths = fix_repo(git)
        commit_cleaned(git, paths, sign=True)
    if start:
        git.run("switch", start)


def _parse_commit(raw: bytes) -> dict[str, object]:
    """Read tree, parents, identities, and message from a commit object."""
    text = raw.decode("utf-8", errors="surrogateescape")
    header, sep, body = text.partition("\n\n")
    if not sep:
        body = ""
    tree = ""
    parents: list[str] = []
    author = ""
    committer = ""
    for line in header.splitlines():
        if line.startswith(" ") or line.startswith("gpgsig"):
            continue
        key, _, value = line.partition(" ")
        if key == "tree":
            tree = value
        elif key == "parent":
            parents.append(value)
        elif key == "author":
            author = value
        elif key == "committer":
            committer = value
    if not tree or not author or not committer:
        raise SystemExit("Cannot read a commit object that would be rewritten.")
    return {
        "tree": tree,
        "parents": parents,
        "author": author,
        "committer": committer,
        "message": body,
    }


def _ident_env(prefix: str, value: str) -> dict[str, str]:
    """Turn a git author or committer line into commit-tree environment variables."""
    if "<" not in value or ">" not in value:
        raise SystemExit(f"Cannot read git identity: {value}")
    name, _, rest = value.partition("<")
    email, _, date = rest.partition(">")
    return {
        f"{prefix}_NAME": name.strip(),
        f"{prefix}_EMAIL": email.strip(),
        f"{prefix}_DATE": date.strip(),
    }


def _list_tree(git: Git, tree: str) -> list[tuple[str, str, str, str]]:
    """Return mode, type, oid, and path for one tree. Does not check out files."""
    result = git.run_bytes("ls-tree", "-z", tree)
    entries: list[tuple[str, str, str, str]] = []
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        meta, name = item.split(b"\t", 1)
        mode, kind, oid = meta.decode("ascii").split(" ")
        path = name.decode("utf-8", errors="surrogateescape")
        entries.append((mode, kind, oid, path))
    return entries


def _rewrite_blob(git: Git, oid: str, cache: dict[str, str]) -> str:
    """Return a blob id with the dropper removed, or the original id when it is clean."""
    if oid in cache:
        return cache[oid]
    data = git.run_bytes("cat-file", "blob", oid).stdout
    updated = strip_bytes(data)
    if updated is None:
        cache[oid] = oid
        return oid
    written = git.run_bytes("hash-object", "-w", "--stdin", input_bytes=updated)
    new_oid = written.stdout.decode("ascii").strip()
    cache[oid] = new_oid
    return new_oid


def _rewrite_tree(git: Git, tree: str, cache: dict[str, str], blobs: dict[str, str]) -> str:
    """Return a tree id with infected code blobs replaced. Unchanged trees keep their id."""
    if tree in cache:
        return cache[tree]
    entries = _list_tree(git, tree)
    changed = False
    rebuilt: list[tuple[str, str, str, str]] = []
    for mode, kind, oid, path in entries:
        new_oid = oid
        if kind == "blob" and is_code_path(path):
            new_oid = _rewrite_blob(git, oid, blobs)
        elif kind == "tree":
            new_oid = _rewrite_tree(git, oid, cache, blobs)
        if new_oid != oid:
            changed = True
        rebuilt.append((mode, kind, new_oid, path))
    if not changed:
        cache[tree] = tree
        return tree
    payload = b"".join(
        f"{mode} {kind} {oid}\t".encode("ascii") + path.encode("utf-8", errors="surrogateescape") + b"\0"
        for mode, kind, oid, path in rebuilt
    )
    written = git.run_bytes("mktree", "-z", input_bytes=payload)
    new_tree = written.stdout.decode("ascii").strip()
    cache[tree] = new_tree
    return new_tree


def _write_commit(git: Git, parsed: dict[str, object], tree: str, parents: list[str], sign: bool) -> str:
    """Create a commit with the original author, committer, dates, and message."""
    env = _ident_env("GIT_AUTHOR", str(parsed["author"]))
    env.update(_ident_env("GIT_COMMITTER", str(parsed["committer"])))
    cmd = ["commit-tree", tree]
    if sign:
        cmd.append("-S")
    for parent in parents:
        cmd.extend(["-p", parent])
    result = git.run(*cmd, input_text=str(parsed["message"]), extra_env=env)
    return result.stdout.strip()


def _selected_refs(git: Git, branch: str | None) -> list[str]:
    """Return the local branch, or every local branch and tag when branch is omitted."""
    if branch:
        ref = f"refs/heads/{branch}"
        exists = git.run("show-ref", "--verify", "--quiet", ref, check=False)
        if exists.returncode != 0:
            raise SystemExit(f"No local branch named {branch}.")
        return [ref]
    return for_each_ref(git, "refs/heads", "refs/tags")


def _refuse_shared(branch: str, blockers: list[tuple[str, bool]]) -> None:
    """Print the recovery and stop before any object or ref is written."""
    print(f"Refusing to rewrite {branch}.")
    print("These refs also reach the infected commits:")
    for ref, contained in blockers:
        label = display_ref(ref)
        if contained and ref.startswith("refs/tags/"):
            print(
                f"  {label}: already contained in {branch}. "
                f"Delete this tag only when you mean to drop it, "
                f"then rerun --rewrite --branch {branch}."
            )
        elif contained:
            print(
                f"  {label}: already contained in {branch}. "
                f"Delete this local ref and the same branch on the remote, "
                f"then rerun --rewrite --branch {branch}."
            )
        else:
            print(f"  {label}: this ref has commits {branch} does not have.")
    if blockers and all(contained for _, contained in blockers):
        print(
            f"Every blocking ref is already contained in {branch}. "
            f"Delete those refs, then rerun --rewrite --branch {branch}."
        )
    else:
        print("Rerun --rewrite with no branch name so the shared commits are replaced once.")
    raise SystemExit(1)


def _blockers(git: Git, branch: str, target: str, infected: set[str]) -> list[tuple[str, bool]]:
    """Return other local branches and tags that reach infected commits on the target."""
    blockers: list[tuple[str, bool]] = []
    for ref in for_each_ref(git, "refs/heads", "refs/tags"):
        if ref == target:
            continue
        if not any(is_ancestor(git, sha, ref) for sha in infected):
            continue
        blockers.append((ref, is_ancestor(git, ref, target)))
    return blockers


def _map_commits(git: Git, refs: list[str], sign: bool) -> dict[str, str]:
    """Map each walked commit to itself or a replacement. Parents are mapped first."""
    order = rev_list(git, "--reverse", "--topo-order", *refs)
    trees: dict[str, str] = {}
    blobs: dict[str, str] = {}
    mapped: dict[str, str] = {}
    for sha in order:
        parsed = _parse_commit(git.run_bytes("cat-file", "commit", sha).stdout)
        old_parents = list(parsed["parents"])
        new_parents = [mapped.get(parent, parent) for parent in old_parents]
        new_tree = _rewrite_tree(git, str(parsed["tree"]), trees, blobs)
        if new_tree == parsed["tree"] and new_parents == old_parents:
            mapped[sha] = sha
            continue
        mapped[sha] = _write_commit(git, parsed, new_tree, new_parents, sign)
    return mapped


def _retag(git: Git, tag_oid: str, commit: str) -> str:
    """Write a copy of an annotated tag that points at commit. A tag signature is dropped."""
    raw = git.run_bytes("cat-file", "tag", tag_oid).stdout.decode("utf-8", errors="surrogateescape")
    header, _, body = raw.partition("\n\n")
    lines: list[str] = []
    skipping = False
    for line in header.splitlines():
        if skipping and line.startswith(" "):
            continue
        skipping = line.startswith("gpgsig")
        if skipping:
            continue
        if line.startswith("type ") and line != "type commit":
            raise SystemExit(f"Tag {tag_oid} does not point at a commit. Retag it by hand.")
        lines.append(f"object {commit}" if line.startswith("object ") else line)
    signed = False
    for marker in ("-----BEGIN PGP SIGNATURE-----", "-----BEGIN SSH SIGNATURE-----", "-----BEGIN SIGNED MESSAGE-----"):
        index = body.find(marker)
        if index != -1:
            body = body[:index]
            signed = True
    if signed or skipping:
        print(f"Tag {tag_oid[:12]} was signed. The rewritten tag is unsigned.")
    payload = "\n".join(lines) + "\n\n" + body
    written = git.run_bytes("mktag", input_bytes=payload.encode("utf-8", errors="surrogateescape"))
    return written.stdout.decode("ascii").strip()


def _new_tip(git: Git, ref: str, mapped: dict[str, str]) -> tuple[str, str]:
    """Return the current and replacement object for ref. Annotated tags get a new tag object."""
    old = git.out("rev-parse", ref).strip()
    commit = git.out("rev-parse", f"{ref}^{{commit}}").strip()
    new_commit = mapped.get(commit, commit)
    if new_commit == commit:
        return old, old
    if old == commit:
        return old, new_commit
    return old, _retag(git, old, new_commit)


def _backup_and_move(git: Git, ref: str, old: str, new: str) -> None:
    """Store the old tip under refs/backup/git-dropper-cleanup, then move ref."""
    backup = f"{BACKUP_PREFIX}/{ref}"
    existing = git.run("show-ref", "--verify", "--quiet", backup, check=False)
    if existing.returncode != 0:
        git.run("update-ref", backup, old)
    git.run("update-ref", ref, new, old)


def _reset_checked_out(git: Git, moved: set[str]) -> None:
    """Point the worktree at the new tip after the checked-out branch moves."""
    result = git.run("symbolic-ref", "--quiet", "HEAD", check=False)
    if result.returncode != 0:
        return
    ref = result.stdout.strip()
    if ref in moved:
        git.run("reset", "--hard")


def rewrite_repo(
    git: Git,
    sign: bool,
    branch: str | None = None,
    *,
    write_report: bool = True,
) -> None:
    """Rewrite infected commits and descendants. Refuse a shared single-branch history.

    Does not check out each commit, does not change git config, and does not push.
    Clean ancestors keep their SHAs. Backup tips are not pushed.
    """
    started = utc_now_iso()
    # URL clones only check out the default branch; create locals for origin/* so
    # --rewrite / --rewrite --branch can move the same tips --check reported.
    ensure_local_branches(git)
    refs = _selected_refs(git, branch)
    if not refs:
        print("No local branches or tags to rewrite.")
        return
    infected_paths = infected_commits(git, rev_list(git, *refs))
    infected = set(infected_paths)
    if branch and infected:
        blockers = _blockers(git, branch, refs[0], infected)
        if blockers:
            _refuse_shared(branch, blockers)
    if not infected:
        label = branch or "the selected refs"
        print(f"No dropper commits on {label}. Nothing was rewritten.")
        return
    require_clean(git)
    if not sign:
        print("No signing key. Rewritten commits will be unsigned.")
        print_signing_help()
    if branch:
        print(f"Rewriting {branch} in {git.repo}")
    else:
        print(f"Rewriting affected branches and tags in {git.repo}")
    mapped = _map_commits(git, refs, sign)
    tips = [(ref, *_new_tip(git, ref, mapped)) for ref in refs]
    moved: set[str] = set()
    ref_rows: list[list[str]] = []
    for ref, old, new in tips:
        if new == old:
            continue
        _backup_and_move(git, ref, old, new)
        moved.add(ref)
        print(f"Moved {display_ref(ref)}")
        ref_rows.append([display_ref(ref), old[:12], new[:12]])
    if not moved:
        print("No refs needed to move.")
        return
    _reset_checked_out(git, moved)
    print(f"Rewrite finished. Backup refs are in {BACKUP_PREFIX} and are not pushed.")
    print("Remote-tracking refs were left on the old commits so a later --push can use --force-with-lease.")
    if write_report:
        commit_rows: list[list[str]] = []
        for old_sha, new_sha in mapped.items():
            if old_sha == new_sha:
                continue
            meta = commit_meta(git, old_sha)
            if old_sha in infected_paths:
                files = ", ".join(infected_paths[old_sha])
            else:
                files = "parent remap"
            commit_rows.append(
                [
                    old_sha[:12],
                    new_sha[:12],
                    meta.author,
                    meta.committer,
                    meta.subject,
                    files,
                ]
            )
        path = write_rewrite_report(
            repo=str(git.repo),
            started=started,
            finished=utc_now_iso(),
            branch_filter=branch,
            signed=sign,
            ref_rows=ref_rows,
            commit_rows=commit_rows,
        )
        print(f"Report written: {path}")
