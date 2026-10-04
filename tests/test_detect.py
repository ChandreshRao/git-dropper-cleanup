"""Text cleanup, with no git repository required."""

from git_dropper_cleanup.detect import read_text, strip_text


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
