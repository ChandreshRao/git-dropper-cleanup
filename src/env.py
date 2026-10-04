"""Load CLONE_ROOT from the .env file next to this project.

The loader uses the standard library. It does not read signing keys.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def read_env_file(path: Path) -> dict[str, str]:
    """Return KEY=VALUE pairs from path. Blank lines and # comments are ignored."""
    if not path.is_file():
        raise SystemExit(
            f"{path} is missing. Copy .env.example to .env and set CLONE_ROOT."
        )
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def clone_root(path: Path | None = None) -> Path:
    """Return the folder where a git URL is cloned. Requires CLONE_ROOT in .env."""
    env_path = ENV_PATH if path is None else path
    values = read_env_file(env_path)
    raw = values.get("CLONE_ROOT", "").strip()
    if not raw:
        raise SystemExit(f"CLONE_ROOT is not set in {env_path}.")
    dest = Path(raw)
    if not dest.is_absolute():
        dest = (env_path.parent / dest).resolve()
    return dest
