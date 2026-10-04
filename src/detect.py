"""Find and remove an appended JavaScript dropper from text.

This module reads and edits text only. It does not run repository code.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    "out",
}
CODE_EXTS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte"}

_QUOTE = "['\"]"
MARKER = re.compile(
    r"global\.o\s*=\s*" + _QUOTE + r"[^'\"]*" + _QUOTE
    + r"|global\[\s*" + _QUOTE + r"!" + _QUOTE + r"\s*\]\s*=\s*" + _QUOTE + r"[^'\"]*" + _QUOTE
    + r"|global\[\s*" + _QUOTE + r"_V" + _QUOTE + r"\s*\]\s*=\s*" + _QUOTE + r"[^'\"]*" + _QUOTE
    + r"|rmcej%otb%"
    + r"|Cot%3t=shtP"
)
SHIM = re.compile(
    r"^(?:import\s+\{\s*createRequire\s*\}\s+from\s+['\"]module['\"];\r?\n"
    r"const\s+require\s*=\s*createRequire\(\s*import\.meta\.url\s*\);\r?\n)"
)
GREP_PATTERN = (
    "global\\.o[[:space:]]*=|"
    "global\\[[[:space:]]*" + _QUOTE + "!" + _QUOTE + "[[:space:]]*\\][[:space:]]*=|"
    "global\\[[[:space:]]*" + _QUOTE + "_V" + _QUOTE + "[[:space:]]*\\][[:space:]]*=|"
    "rmcej%otb%|Cot%3t=shtP"
)


def is_code_path(path: str) -> bool:
    """Return whether this repository path is a code file the cleaner edits."""
    return Path(path).suffix.lower() in CODE_EXTS


def strip_text(text: str) -> str | None:
    """Return text with the dropper removed, or None when the text is unchanged.

    A leading createRequire shim is removed only when the remaining file does not call require.
    """
    match = MARKER.search(text)
    if not match:
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    cut = text[: match.start()].rstrip(" \t")
    if cut and not cut.endswith(("\n", "\r")):
        cut += newline
    without_shim = SHIM.sub("", cut, count=1)
    if without_shim != cut and not re.search(r"\brequire\s*\(", without_shim):
        cut = without_shim
    if cut == text:
        return None
    return cut


def walk_code_files(root: Path) -> list[Path]:
    """Return code files under root, skipping dependency and build directories and symlinks.

    A symlink can point outside the clone, so it is never read or written.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in CODE_EXTS and not path.is_symlink():
                found.append(path)
    return found


def read_text(path: Path) -> str | None:
    """Read a file as text, or return None when it contains a NUL byte."""
    data = path.read_bytes()
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="surrogateescape")


def tasks_marker(root: Path) -> Path | None:
    """Return .vscode/tasks.json when it contains the marker. The file is never edited."""
    tasks = root / ".vscode" / "tasks.json"
    if tasks.parent.is_symlink() or tasks.is_symlink() or not tasks.is_file():
        return None
    text = read_text(tasks)
    if text and MARKER.search(text):
        return tasks
    return None


def clean_tree(root: Path, write: bool) -> tuple[list[Path], list[Path]]:
    """Return infected code files and tasks.json hits. Write only when write is true."""
    code_hits: list[Path] = []
    for path in walk_code_files(root):
        text = read_text(path)
        if text is None or not MARKER.search(text):
            continue
        code_hits.append(path)
        if not write:
            continue
        updated = strip_text(text)
        if updated is None:
            continue
        path.write_bytes(updated.encode("utf-8", errors="surrogateescape"))
    tasks = tasks_marker(root)
    return code_hits, [tasks] if tasks else []


def rel(root: Path, path: Path) -> str:
    """Return path relative to root, or the original path when it is outside root."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def strip_bytes(data: bytes) -> bytes | None:
    """Return stripped file bytes, or None when the blob is binary or unchanged."""
    if b"\0" in data:
        return None
    text = data.decode("utf-8", errors="surrogateescape")
    updated = strip_text(text)
    if updated is None:
        return None
    return updated.encode("utf-8", errors="surrogateescape")
