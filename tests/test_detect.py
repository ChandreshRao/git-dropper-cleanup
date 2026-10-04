"""Text cleanup, with no git repository required."""

import pytest

from git_dropper_cleanup.detect import clean_tree, read_text, strip_text


def test_strip_marker() -> None:
    text = "function ok() {}\nglobal.o = \"x\"\n"
    assert strip_text(text) == "function ok() {}\n"


def test_clean_file_is_unchanged() -> None:
    assert strip_text("const x = 1;\n") is None


def test_shim_removed_when_require_is_unused() -> None:
    text = (
        "import { createRequire } from 'module';\n"
        "const require = createRequire(import.meta.url);\n"
        "const x = 1;\n"
        "global.o = \"x\"\n"
    )
    result = strip_text(text)
    assert result is not None
    assert "createRequire" not in result
    assert "const x = 1;\n" in result


def test_shim_kept_when_require_is_used() -> None:
    text = (
        "import { createRequire } from 'module';\n"
        "const require = createRequire(import.meta.url);\n"
        "const fs = require('fs');\n"
        "global.o = \"x\"\n"
    )
    result = strip_text(text)
    assert result is not None
    assert "createRequire" in result
    assert "require('fs')" in result


def test_binary_file_is_skipped(tmp_path) -> None:
    path = tmp_path / "a.js"
    path.write_bytes(b"\0\x01")
    assert read_text(path) is None


def test_symlinked_code_file_is_not_followed(tmp_path) -> None:
    outside = tmp_path / "outside.js"
    outside.write_text("keep\nglobal.o = \"x\"\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        (repo / "link.js").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")
    hits, _tasks = clean_tree(repo, write=True)
    assert hits == []
    assert "global.o" in outside.read_text(encoding="utf-8")
