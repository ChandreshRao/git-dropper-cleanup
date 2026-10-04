"""CLONE_ROOT is read from .env and a URL is refused when it is missing."""

from pathlib import Path

import pytest

from git_dropper_cleanup.env import clone_root
from git_dropper_cleanup.gitio import parse_clone_dest
from git_dropper_cleanup.__main__ import main


def test_env_supplies_clone_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    dest = tmp_path / "clean"
    env.write_text(f"CLONE_ROOT={dest}\n", encoding="utf-8")
    monkeypatch.setattr("git_dropper_cleanup.env.ENV_PATH", env)
    assert parse_clone_dest("https://github.com/acme/widget.git") == dest / "acme" / "widget"


def test_relative_clone_root_is_next_to_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("CLONE_ROOT=clean\n", encoding="utf-8")
    assert clone_root(env) == (tmp_path / "clean").resolve()


def test_url_clone_refused_when_env_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("git_dropper_cleanup.env.ENV_PATH", tmp_path / "missing.env")
    with pytest.raises(SystemExit, match="CLONE_ROOT"):
        main(["https://github.com/acme/widget.git", "--check"])


def test_url_clone_refused_when_clone_root_blank(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("git_dropper_cleanup.env.ENV_PATH", env)
    with pytest.raises(SystemExit, match="CLONE_ROOT"):
        main(["https://github.com/acme/widget.git"])
