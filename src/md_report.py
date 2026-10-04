"""Write markdown reports under the tool repo reports/<slug>/ directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from git_dropper_cleanup.gitio import Git

_DEFAULT_REPORT_ROOT: Path | None = None


def tool_root() -> Path:
    """Return the git-dropper-cleanup repository root."""
    return Path(__file__).resolve().parent.parent


def report_root() -> Path:
    """Return the directory that holds per-repo report folders."""
    global _DEFAULT_REPORT_ROOT
    if _DEFAULT_REPORT_ROOT is not None:
        return _DEFAULT_REPORT_ROOT
    return tool_root() / "reports"


def set_report_root(path: Path | None) -> None:
    """Override report output root (tests). Pass None to reset."""
    global _DEFAULT_REPORT_ROOT
    _DEFAULT_REPORT_ROOT = path


def repo_slug(repo_path: str | Path) -> str:
    """Sanitize a clone path into a folder name under reports/."""
    name = Path(repo_path).name or "repo"
    safe = re.sub(r"[^\w.\-]+", "-", name).strip("-")
    return safe or "repo"


def report_path(repo_path: str | Path, kind: str) -> Path:
    """Build a timestamped report file path for check, rewrite, or push."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return report_root() / repo_slug(repo_path) / f"{kind}-{stamp}.md"


def write_text(path: Path, body: str) -> Path:
    """Write body to path, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def escape_cell(text: str) -> str:
    """Escape pipe characters for markdown tables."""
    return text.replace("|", "\\|").replace("\n", " ")


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Return a GitHub-flavored markdown table."""
    if not rows:
        return "_None._\n"
    head = "| " + " | ".join(escape_cell(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = [
        "| " + " | ".join(escape_cell(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([head, sep, *body_lines]) + "\n"


@dataclass(frozen=True)
class CommitMeta:
    """Author, committer, and subject for one commit."""

    author: str
    committer: str
    subject: str


def commit_meta(git: Git, sha: str) -> CommitMeta:
    """Read author, committer, and subject without printing the payload."""
    fmt = "%an <%ae>%x00%cn <%ce>%x00%s"
    line = git.out("show", "-s", "--format=" + fmt, sha)
    parts = line.split("\0", 2)
    if len(parts) != 3:
        return CommitMeta("—", "—", "—")
    return CommitMeta(author=parts[0], committer=parts[1], subject=parts[2])


def utc_now_iso() -> str:
    """Return current UTC time for report headers."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def write_check_report(
    *,
    repo: str,
    worktree_label: str,
    code_hits: list[str],
    task_hits: list[str],
    branch_rows: list[list[str]],
    tag_rows: list[list[str]],
    remote_rows: list[list[str]],
    clean_refs: list[str],
    commit_rows: list[list[str]],
    backup_note: str | None,
    exit_code: int,
) -> Path:
    """Write the check markdown report."""
    path = report_path(repo, "check")
    lines = [
        "# git-dropper-cleanup check report",
        "",
        f"- **Repository:** `{repo}`",
        f"- **Generated:** {utc_now_iso()}",
        f"- **Exit code:** {exit_code}",
        "",
        "## Worktree",
        "",
    ]
    if code_hits:
        lines.append(f"Branch `{worktree_label}` has dropper markers in:")
        for hit in code_hits:
            lines.append(f"- `{hit}`")
    else:
        lines.append(f"Worktree (`{worktree_label}`): **clean**")
    lines.append("")
    if task_hits:
        for hit in task_hits:
            lines.append(f"- tasks.json marker (not edited): `{hit}`")
        lines.append("")
    lines.extend(["## Branches", "", md_table(["Branch", "Status", "Affected count"], branch_rows)])
    lines.extend(["## Tags", "", md_table(["Tag", "Status", "Affected count"], tag_rows)])
    lines.extend(["## Remotes", "", md_table(["Remote", "Status", "Affected count"], remote_rows)])
    lines.extend(["## Clean refs", ""])
    if clean_refs:
        for ref in clean_refs:
            lines.append(f"- {ref}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.extend(
        [
            "## Affected commits",
            "",
            md_table(
                ["Short SHA", "Author", "Committer", "Subject", "Files", "Reached by"],
                commit_rows,
            ),
        ]
    )
    if backup_note:
        lines.extend(["## Backup", "", backup_note, ""])
    return write_text(path, "\n".join(lines))


def write_rewrite_report(
    *,
    repo: str,
    started: str,
    finished: str,
    branch_filter: str | None,
    signed: bool,
    ref_rows: list[list[str]],
    commit_rows: list[list[str]],
) -> Path:
    """Write the rewrite markdown report."""
    path = report_path(repo, "rewrite")
    filter_line = branch_filter or "(all local branches and tags)"
    lines = [
        "# git-dropper-cleanup rewrite report",
        "",
        f"- **Repository:** `{repo}`",
        f"- **Started:** {started}",
        f"- **Finished:** {finished}",
        f"- **Branch filter:** {filter_line}",
        f"- **Signed commits:** {'yes' if signed else 'no'}",
        "",
        "## Refs moved",
        "",
        md_table(["Ref", "Old tip", "New tip"], ref_rows),
        "## Commits rewritten",
        "",
        md_table(
            ["Old SHA", "New SHA", "Author", "Committer", "Subject", "Files cleaned"],
            commit_rows,
        ),
    ]
    return write_text(path, "\n".join(lines))


@dataclass(frozen=True)
class PushOutcome:
    """One ref push attempt."""

    ref: str
    kind: str
    result: str
    detail: str


def write_push_report(
    *,
    repo: str,
    rewritten: bool,
    only_branch: str | None,
    push_main: bool,
    outcomes: list[PushOutcome],
    refused: str | None,
    exit_code: int,
) -> Path:
    """Write the push markdown report."""
    path = report_path(repo, "push")
    lines = [
        "# git-dropper-cleanup push report",
        "",
        f"- **Repository:** `{repo}`",
        f"- **Generated:** {utc_now_iso()}",
        f"- **Force-with-lease:** {'yes' if rewritten else 'no'}",
        f"- **Branch filter:** {only_branch or '(all local branches)'}",
        f"- **Push main/master:** {'yes' if push_main else 'no'}",
        f"- **Exit code:** {exit_code}",
        "",
    ]
    if refused:
        lines.extend(["## Refused", "", refused, ""])
    rows = [[o.ref, o.kind, o.result, o.detail] for o in outcomes]
    pushed = sum(1 for o in outcomes if o.result == "pushed")
    failed = [o.ref for o in outcomes if o.result == "failed"]
    lines.extend(
        [
            "## Attempted refs",
            "",
            md_table(["Ref", "Kind", "Result", "Detail"], rows),
            "## Summary",
            "",
            f"- Pushed: {pushed}",
            f"- Failed: {', '.join(failed) if failed else 'none'}",
            "",
        ]
    )
    return write_text(path, "\n".join(lines))
