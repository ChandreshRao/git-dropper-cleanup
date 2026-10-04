"""Rewrite a temporary sample repository. No network and no push."""

from pathlib import Path
import subprocess

import pytest

from git_dropper_cleanup.gitio import GIT, Git, signing_key
from git_dropper_cleanup.__main__ import main

BACKUP = "refs/backup/git-dropper-cleanup/refs/heads/main"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in the sample repository."""
    result = subprocess.run(
        [GIT, "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr or result.stdout}")
    return result


def rev(repo: Path, ref: str = "HEAD") -> str:
    """Return the full SHA for ref."""
    return git(repo, "rev-parse", ref).stdout.strip()


def init_repo(path: Path) -> Path:
    """Create a sample repo that will not use the operator's signing key."""
    repo = path / "sample"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "gpg.format", "ssh")
    git(repo, "config", "user.signingkey", str(repo / "missing.pub"))
    return repo


def commit_file(repo: Path, content: str, message: str) -> str:
    """Write a.js, commit it, and return the new SHA."""
    (repo / "a.js").write_bytes(content.encode("utf-8"))
    git(repo, "add", "--", "a.js")
    git(repo, "commit", "-m", message)
    return rev(repo)


def infected_history(path: Path) -> tuple[Path, str, str, str]:
    """Build a clean root, an infected commit, and an infected descendant."""
    repo = init_repo(path)
    first = commit_file(repo, "ok\n", "clean")
    second = commit_file(repo, "ok\nglobal.o = \"x\"\n", "infected")
    third = commit_file(repo, "changed\nglobal.o = \"x\"\n", "still infected")
    return repo, first, second, third


def test_check_lists_clean_branch_and_affected_commit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _first, second, _third = infected_history(tmp_path)
    git(repo, "branch", "other", "HEAD~2")
    status = main(["--no-report", "--check", str(repo)])
    output = capsys.readouterr().out
    assert status == 1
    assert "other: clean" in output
    assert second[:12] in output
    assert "main: 2 affected commits" in output


def test_full_rewrite_keeps_clean_ancestor(tmp_path: Path) -> None:
    repo, first, second, third = infected_history(tmp_path)
    git(repo, "branch", "other", first)
    main(["--no-report", "--rewrite", str(repo)])
    assert rev(repo, "main~2") == first
    assert rev(repo, "main") != third
    assert rev(repo, "main^") != second
    assert rev(repo, "other") == first
    assert "global.o" not in git(repo, "show", "main:a.js").stdout
    assert "global.o" not in (repo / "a.js").read_text(encoding="utf-8")
    assert rev(repo, BACKUP) == third


def test_branch_refuses_when_sibling_is_not_contained(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, first, second, third = infected_history(tmp_path)
    git(repo, "checkout", "-b", "side", second)
    commit_file(repo, "side\nglobal.o = \"x\"\n", "side keeps the dropper")
    git(repo, "checkout", "main")
    with pytest.raises(SystemExit):
        main(["--no-report", "--rewrite", "--branch", "main", str(repo)])
    output = capsys.readouterr().out
    assert "no branch name" in output
    assert rev(repo, "main") == third
    missing = git(repo, "show-ref", "--verify", "--quiet", BACKUP, check=False)
    assert missing.returncode != 0

    main(["--no-report", "--rewrite", str(repo)])
    assert rev(repo, "main^") == rev(repo, "side^")
    assert rev(repo, "main^") != second
    assert rev(repo, "main~2") == first
    assert rev(repo, "side~2") == first
    assert "global.o" not in git(repo, "show", "main:a.js").stdout
    assert "global.o" not in git(repo, "show", "side:a.js").stdout


def test_merged_feature_is_rewritten_with_the_target_after_delete(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, first, second, third = infected_history(tmp_path)
    git(repo, "branch", "feature", second)
    with pytest.raises(SystemExit):
        main(["--no-report", "--rewrite", "--branch", "main", str(repo)])
    output = capsys.readouterr().out
    assert "already contained in main" in output
    assert rev(repo, "main") == third
    assert rev(repo, "feature") == second

    git(repo, "branch", "-D", "feature")
    main(["--no-report", "--rewrite", "--branch", "main", str(repo)])
    assert rev(repo, "main~2") == first
    assert rev(repo, "main") != third
    assert "global.o" not in git(repo, "show", "main:a.js").stdout
    missing = git(repo, "show-ref", "--verify", "--quiet", "refs/heads/feature", check=False)
    assert missing.returncode != 0


def test_full_rewrite_moves_annotated_tag(tmp_path: Path) -> None:
    repo, first, _second, third = infected_history(tmp_path)
    git(repo, "tag", "-a", "v1", "-m", "release one")
    old_tag = rev(repo, "refs/tags/v1")
    main(["--no-report", "--rewrite", str(repo)])
    assert git(repo, "cat-file", "-t", "refs/tags/v1").stdout.strip() == "tag"
    assert rev(repo, "refs/tags/v1^{commit}") == rev(repo, "main")
    assert rev(repo, "refs/tags/v1") != old_tag
    assert rev(repo, "v1~2") == first
    assert "release one" in git(repo, "cat-file", "tag", "refs/tags/v1").stdout
    assert "global.o" not in git(repo, "show", "v1:a.js").stdout
    assert rev(repo, "refs/backup/git-dropper-cleanup/refs/tags/v1") == old_tag
    assert rev(repo, BACKUP) == third


def test_branches_refuses_dirty_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _first, _second, third = infected_history(tmp_path)
    (repo / "staged.txt").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", "--", "staged.txt")
    monkeypatch.setattr("git_dropper_cleanup.__main__.signing_key", lambda _git: "key")
    with pytest.raises(SystemExit, match="uncommitted changes"):
        main(["--no-report", "--branches", str(repo)])
    assert rev(repo, "main") == third


def test_gpg_key_id_is_kept_and_missing_ssh_file_is_dropped(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    wrapper = Git(repo, tmp_path / "hooks")
    git(repo, "config", "gpg.format", "openpgp")
    git(repo, "config", "user.signingkey", "3AA5C34371567BD2")
    assert signing_key(wrapper) == "3AA5C34371567BD2"
    git(repo, "config", "gpg.format", "ssh")
    git(repo, "config", "user.signingkey", str(repo / "missing.pub"))
    assert signing_key(wrapper) == ""


def has_ref(repo: Path, ref: str) -> bool:
    """Return whether ref exists in the sample repository."""
    return git(repo, "show-ref", "--verify", "--quiet", ref, check=False).returncode == 0


def configure(repo: Path) -> None:
    """Set the sample identity so commits do not use the operator's key."""
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")


def remote_style_clone(tmp_path: Path) -> tuple[Path, str, str]:
    """Return a clone with only local main, plus the clean and infected SHAs.

    origin/feature points at the infected commit. origin/side diverges from it.
    main on the clone is that infected commit, matching a URL clone of this history.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    configure(origin)
    first = commit_file(origin, "ok\n", "clean")
    infected = commit_file(origin, "ok\nglobal.o = \"x\"\n", "infected")
    git(origin, "branch", "feature", infected)
    git(origin, "checkout", "-b", "side", infected)
    commit_file(origin, "side\nglobal.o = \"x\"\n", "side keeps the dropper")
    git(origin, "checkout", "main")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(origin), str(clone))
    return clone, first, infected


def test_branch_rewrite_ignores_remote_only_siblings(tmp_path: Path) -> None:
    clone, first, infected = remote_style_clone(tmp_path)
    assert not has_ref(clone, "refs/heads/side")
    main(["--no-report", "--rewrite", "--branch", "main", str(clone)])
    assert not has_ref(clone, "refs/heads/side")
    assert not has_ref(clone, "refs/heads/feature")
    assert rev(clone, "main") != infected
    assert rev(clone, "main^") == first
    assert "global.o" not in git(clone, "show", "main:a.js").stdout


def test_refused_rewrite_does_not_create_remote_branches(tmp_path: Path) -> None:
    repo, _first, second, third = infected_history(tmp_path)
    git(repo, "branch", "side", second)
    git(repo, "update-ref", "refs/remotes/origin/extra", third)
    with pytest.raises(SystemExit):
        main(["--no-report", "--rewrite", "--branch", "main", str(repo)])
    assert rev(repo, "main") == third
    assert rev(repo, "side") == second
    assert not has_ref(repo, "refs/heads/extra")
    assert not has_ref(repo, "refs/backup/git-dropper-cleanup/refs/heads/main")


def test_clean_rewrite_does_not_materialize_origin_branches(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    configure(origin)
    first = commit_file(origin, "ok\n", "clean")
    git(origin, "branch", "docs", first)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(origin), str(clone))
    main(["--no-report", "--rewrite", str(clone)])
    assert not has_ref(clone, "refs/heads/docs")
    assert rev(clone, "main") == first


def test_dirty_rewrite_does_not_materialize_origin_branches(tmp_path: Path) -> None:
    clone, _first, infected = remote_style_clone(tmp_path)
    (clone / "dirty.txt").write_text("unrelated\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="uncommitted changes"):
        main(["--no-report", "--rewrite", str(clone)])
    assert not has_ref(clone, "refs/heads/feature")
    assert not has_ref(clone, "refs/heads/side")
    assert rev(clone, "main") == infected


def test_full_rewrite_materializes_infected_origin_branches(tmp_path: Path) -> None:
    clone, first, infected = remote_style_clone(tmp_path)
    git(clone, "reset", "--hard", first)
    git(clone, "update-ref", "refs/remotes/origin/main", first)
    main(["--no-report", "--rewrite", str(clone)])
    assert has_ref(clone, "refs/heads/feature")
    assert has_ref(clone, "refs/heads/side")
    assert rev(clone, "main") == first
    assert rev(clone, "feature") != infected
    assert "global.o" not in git(clone, "show", "feature:a.js").stdout
    assert "global.o" not in git(clone, "show", "side:a.js").stdout


def test_rewrite_one_origin_branch_leaves_siblings_remote(tmp_path: Path) -> None:
    clone, first, infected = remote_style_clone(tmp_path)
    git(clone, "reset", "--hard", first)
    main(["--no-report", "--rewrite", "--branch", "feature", str(clone)])
    assert has_ref(clone, "refs/heads/feature")
    assert not has_ref(clone, "refs/heads/side")
    assert rev(clone, "main") == first
    assert rev(clone, "feature") != infected
    assert "global.o" not in git(clone, "show", "feature:a.js").stdout


def test_origin_branch_name_conflict_creates_nothing(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    infected = commit_file(repo, "ok\nglobal.o = \"x\"\n", "infected")
    git(repo, "branch", "feature", infected)
    git(repo, "update-ref", "refs/remotes/origin/feature/x", infected)
    with pytest.raises(SystemExit, match="conflicts"):
        main(["--no-report", "--rewrite", str(repo)])
    assert rev(repo, "main") == infected
    assert rev(repo, "feature") == infected
    assert not has_ref(repo, "refs/heads/feature/x")


def test_one_infected_branch_leaves_the_clean_branch(tmp_path: Path) -> None:
    repo, first, _second, third = infected_history(tmp_path)
    git(repo, "branch", "other", first)
    main(["--no-report", "--rewrite", "--branch", "main", str(repo)])
    assert rev(repo, "other") == first
    assert rev(repo, "main~2") == first
    assert rev(repo, "main") != third
    assert rev(repo, BACKUP) == third
