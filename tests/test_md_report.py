"""Markdown report files for check, rewrite, and push."""

from pathlib import Path

import pytest

from git_dropper_cleanup.gitio import Git
from git_dropper_cleanup.md_report import (
    PushOutcome,
    md_table,
    repo_slug,
    report_path,
    set_report_root,
    write_error_report,
    write_push_report,
)
from git_dropper_cleanup.report import check_repo
from git_dropper_cleanup.rewrite import rewrite_repo
from tests.test_rewrite import infected_history, init_repo, git, rev


@pytest.fixture(autouse=True)
def isolated_report_root(tmp_path: Path) -> None:
    """Write reports under the pytest temp dir."""
    set_report_root(tmp_path / "reports")
    yield
    set_report_root(None)


def test_md_table_escapes_pipes() -> None:
    table = md_table(["A", "B"], [["x|y", "ok"]])
    assert "x\\|y" in table


def test_md_table_escapes_newlines() -> None:
    table = md_table(["A"], [["line\nbreak"]])
    data = [line for line in table.splitlines() if "line" in line]
    assert data == ["| line break |"]


def test_report_slug_keeps_owners_apart_and_does_not_overwrite(tmp_path: Path) -> None:
    left = repo_slug(Path("clones/owner-a/repo"))
    right = repo_slug(Path("clones/owner-b/repo"))
    assert left != right
    assert left == "owner-a-repo"
    assert right == "owner-b-repo"
    first = report_path(Path("clones/owner-a/repo"), "check")
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("one\n", encoding="utf-8")
    second = report_path(Path("clones/owner-a/repo"), "check")
    assert second != first
    assert second.parent == first.parent
    assert first.read_text(encoding="utf-8") == "one\n"


def test_check_writes_report(tmp_path: Path) -> None:
    repo, _first, second, _third = infected_history(tmp_path)
    git = Git(repo, tmp_path / "hooks")
    status = check_repo(git, write_report=True)
    assert status == 1
    reports = list((tmp_path / "reports" / repo_slug(repo)).glob("check-*.md"))
    assert len(reports) == 1
    body = reports[0].read_text(encoding="utf-8")
    assert "## Branches" in body
    assert "main" in body
    assert second[:12] in body
    assert "Test User" in body
    assert "a.js" in body


def test_check_skips_report_when_disabled(tmp_path: Path) -> None:
    repo, *_ = infected_history(tmp_path)
    git = Git(repo, tmp_path / "hooks")
    check_repo(git, write_report=False)
    assert not list((tmp_path / "reports").rglob("*.md"))


def test_rewrite_writes_mapping_report(tmp_path: Path) -> None:
    repo, first, second, third = infected_history(tmp_path)
    git = Git(repo, tmp_path / "hooks")
    rewrite_repo(git, sign=False, write_report=True)
    reports = list((tmp_path / "reports" / repo_slug(repo)).glob("rewrite-*.md"))
    assert len(reports) == 1
    body = reports[0].read_text(encoding="utf-8")
    assert "## Commits rewritten" in body
    assert second[:12] in body
    assert third[:12] in body
    assert rev(repo, "main~2") == first


def test_push_report_builder(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    path = write_push_report(
        repo=str(repo),
        rewritten=True,
        only_branch="main",
        push_main=False,
        outcomes=[
            PushOutcome("main", "branch", "failed", "protected"),
        ],
        refused="Refusing to force-push main without --push-main.",
        exit_code=1,
    )
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "## Refused" in body
    assert "main" in body


def test_error_report_contains_runtime_diagnostics() -> None:
    error = SystemExit("git grep failed: exit -9 (SIGKILL)")
    path = write_error_report(
        error=error,
        argv=["--check", "https://user:secret@example.com/acme/repo.git"],
        mode="check",
        traceback_text="example traceback",
    )
    body = path.read_text(encoding="utf-8")
    assert "git grep failed: exit -9 (SIGKILL)" in body
    assert "example traceback" in body
    assert "Git version" in body
    assert "https://***@example.com/acme/repo.git" in body
    assert "secret" not in body


def test_main_writes_error_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from git_dropper_cleanup.__main__ import main

    missing = tmp_path / "not-a-repo"
    with pytest.raises(SystemExit, match="not a git repo"):
        main(["--check", str(missing)])
    reports = list((tmp_path / "reports" / "errors").glob("error-*.md"))
    assert len(reports) == 1
    assert str(missing) in reports[0].read_text(encoding="utf-8")
    assert "Error report written:" in capsys.readouterr().err


def test_main_no_report_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from git_dropper_cleanup.__main__ import main

    repo, *_ = infected_history(tmp_path)
    main(["--no-report", "--check", str(repo)])
    assert "Report written:" not in capsys.readouterr().out
    assert not list((tmp_path / "reports").rglob("check-*.md"))
