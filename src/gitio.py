"""Run git for one repository without changing git config.

Every command sets core.hooksPath to an empty directory so repository hooks do not run.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from git_dropper_cleanup.env import clone_root

SIGNING_HELP = """
No signing key is configured. This script will not run git config.
Rewritten commits stay unsigned until you set a key and run --rewrite again.
See docs/signing.md in this repository for SSH or GPG setup.
""".strip()
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


def find_git() -> str:
    """Return a git executable from PATH or the usual Windows install locations."""
    for candidate in (
        "git",
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ):
        if candidate == "git":
            from shutil import which

            found = which("git")
            if found:
                return found
            continue
        if Path(candidate).exists():
            return candidate
    raise SystemExit("git was not found. Install Git and open a shell where git runs.")


GIT = find_git()


def returncode_text(returncode: int) -> str:
    """Describe a subprocess return code, including the signal that killed it."""
    if returncode >= 0:
        return str(returncode)
    number = -returncode
    portable_names = {
        2: "SIGINT",
        6: "SIGABRT",
        9: "SIGKILL",
        10: "SIGBUS",
        11: "SIGSEGV",
        15: "SIGTERM",
    }
    try:
        name = signal.Signals(number).name
    except ValueError:
        name = portable_names.get(number, f"signal {number}")
    return f"{returncode} ({name})"


def command_failure(returncode: int, stderr: str, stdout: str = "") -> str:
    """Return actionable diagnostics for a failed subprocess."""
    detail = (stderr or stdout).strip()
    if not detail:
        detail = "no error output; the process may have been killed by the operating system"
    return f"exit {returncode_text(returncode)}: {detail}"


def git_exec(
    cmd: list[str],
    *,
    input_text: str | None = None,
    input_bytes: bytes | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Run a command, retrying a failed host lookup. Does not change git config."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if extra_env:
        env.update(extra_env)
    binary = input_bytes is not None
    result: subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes] | None = None
    for attempt in range(1, 6):
        if binary:
            result = subprocess.run(
                cmd,
                input=input_bytes,
                capture_output=True,
                env=env,
            )
            detail = (result.stderr or b"").decode("utf-8", errors="replace")
        else:
            result = subprocess.run(
                cmd,
                input=input_text,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
                capture_output=True,
                env=env,
            )
            detail = result.stderr or result.stdout or ""
        if result.returncode == 0 or "Could not resolve host" not in detail or attempt == 5:
            return result
        print(f"Could not resolve host (attempt {attempt}/5). Retrying.")
        time.sleep(2)
    assert result is not None
    return result


class Git:
    """Git commands for one clone, with repository hooks disabled."""

    def __init__(self, repo: Path, hooks: Path):
        """Point later commands at repo and an empty hooks directory."""
        self.repo = repo
        self.hooks = hooks

    def _cmd(self, args: tuple[str, ...]) -> list[str]:
        """Build a git command that cannot run hooks from the repository."""
        return [GIT, "-c", f"core.hooksPath={self.hooks}", "-C", str(self.repo), *args]

    def run(
        self,
        *args: str,
        check: bool = True,
        input_text: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run git and raise SystemExit when check is set and the command fails."""
        result = git_exec(self._cmd(args), input_text=input_text, extra_env=extra_env)
        assert isinstance(result, subprocess.CompletedProcess)
        if check and result.returncode != 0:
            detail = command_failure(result.returncode, result.stderr, result.stdout)
            raise SystemExit(f"git {' '.join(args)} failed in {self.repo}: {detail}")
        return result

    def run_bytes(
        self,
        *args: str,
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run git and capture stdout as bytes so file contents stay unchanged."""
        payload = input_bytes if input_bytes is not None else b""
        result = git_exec(self._cmd(args), input_bytes=payload)
        if check and result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            stdout = (result.stdout or b"").decode("utf-8", errors="replace")
            detail = command_failure(result.returncode, stderr, stdout)
            raise SystemExit(f"git {' '.join(args)} failed in {self.repo}: {detail}")
        return result

    def out(self, *args: str) -> str:
        """Return stdout from a git command that must succeed."""
        return self.run(*args).stdout


def is_url(value: str) -> bool:
    """Return whether value looks like a git remote URL."""
    return value.startswith(("https://", "http://", "ssh://", "git@"))


def parse_clone_dest(url: str) -> Path:
    """Return CLONE_ROOT/owner/repo for a git URL. Requires CLONE_ROOT in .env."""
    if url.startswith("git@"):
        path = url.split(":", 1)[-1]
    else:
        path = urlparse(url).path
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise SystemExit(f"Cannot tell owner and repo from URL: {url}")
    owner, repo = parts[-2], parts[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    for part in (owner, repo):
        if not SAFE_SEGMENT.fullmatch(part) or part in (".", ".."):
            raise SystemExit(f"Cannot use {part!r} from URL {redact_url(url)} as a folder name.")
    return clone_root() / owner / repo


def redact_url(url: str) -> str:
    """Return url with any username or token replaced, so it can be printed."""
    if url.startswith("git@"):
        return url
    parsed = urlparse(url)
    if "@" not in parsed.netloc:
        return url
    host = parsed.netloc.rsplit("@", 1)[1]
    return parsed._replace(netloc=f"***@{host}").geturl()


def clone_url(url: str, hooks: Path) -> Path:
    """Clone url under CLONE_ROOT, or reuse an existing clone. Does not run repo code."""
    dest = parse_clone_dest(url)
    shown = redact_url(url)
    if dest.exists():
        if not (dest / ".git").exists():
            raise SystemExit(f"{dest} exists and is not a git clone")
        print(f"Using existing clone {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Cloning {shown} to {dest}")
    result = git_exec(
        [GIT, "-c", f"core.hooksPath={hooks}", "clone", url, str(dest)]
    )
    if result.returncode != 0:
        detail = command_failure(result.returncode, result.stderr, result.stdout).replace(url, shown)
        userinfo = urlparse(url).netloc.rpartition("@")[0] if not url.startswith("git@") else ""
        if userinfo:
            detail = detail.replace(userinfo, "***")
        raise SystemExit(f"Clone failed: {detail}")
    return dest


def resolve_targets(raw: list[str], all_in_dir: bool, hooks: Path) -> list[Path]:
    """Turn URLs and paths into clone directories. A URL requires CLONE_ROOT."""
    if not raw:
        raise SystemExit("Pass a git URL or a repo path. See README.md.")
    targets: list[Path] = []
    for item in raw:
        if is_url(item):
            targets.append(clone_url(item, hooks))
            continue
        path = Path(item).resolve()
        if (path / ".git").exists():
            targets.append(path)
            continue
        if all_in_dir and path.is_dir():
            children = sorted(
                child for child in path.iterdir() if child.is_dir() and (child / ".git").exists()
            )
            if not children:
                raise SystemExit(f"No clones under {path}")
            targets.extend(children)
            continue
        raise SystemExit(
            f"{path} is not a git repo. Pass a repo path, a git URL, or --all-in-dir on a folder of clones."
        )
    return targets


def rev_list(git: Git, *args: str) -> list[str]:
    """Return commit SHAs from git rev-list, or an empty list when the rev is missing."""
    listed = git.run("rev-list", *args, check=False)
    if listed.returncode != 0:
        return []
    return [line for line in listed.stdout.splitlines() if line]


def for_each_ref(git: Git, *namespaces: str) -> list[str]:
    """Return full ref names under the given namespaces, skipping remote HEAD pointers."""
    listed = git.run("for-each-ref", "--format=%(refname)", *namespaces, check=False)
    if listed.returncode != 0:
        return []
    return [ref for ref in listed.stdout.splitlines() if ref and not ref.endswith("/HEAD")]


def display_ref(ref: str) -> str:
    """Return a short label for a heads, tags, or remotes ref."""
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :]
    if ref.startswith("refs/remotes/"):
        return ref[len("refs/remotes/") :]
    if ref.startswith("refs/tags/"):
        return "tag " + ref[len("refs/tags/") :]
    return ref


def local_branches(git: Git) -> list[str]:
    """Return short names of local branches."""
    text = git.out("for-each-ref", "--format=%(refname:short)", "refs/heads")
    return [line for line in text.splitlines() if line]


def current_branch(git: Git) -> str:
    """Return the checked-out branch name, or an empty string when HEAD is detached."""
    result = git.run("branch", "--show-current", check=False)
    return result.stdout.strip()


def is_ancestor(git: Git, ancestor: str, descendant: str) -> bool:
    """Return whether ancestor is reachable from descendant, including equality."""
    result = git.run("merge-base", "--is-ancestor", ancestor, descendant, check=False)
    return result.returncode == 0


def signing_key(git: Git) -> str:
    """Return the configured signing key, or an empty string. Does not change git config."""
    result = git.run("config", "--get", "user.signingkey", check=False)
    if result.returncode != 0:
        return ""
    key = result.stdout.strip()
    if not key or key.startswith(("ssh-", "key::")):
        return key
    fmt = git.run("config", "--get", "gpg.format", check=False).stdout.strip() or "openpgp"
    if fmt != "ssh":
        return key
    path = Path(os.path.expanduser(key))
    if path.is_file():
        return key
    print(f"Signing key file is missing ({path}). Rewritten commits will be unsigned.")
    return ""


def print_signing_help() -> None:
    """Print how an operator can configure signing later. Does not run git config."""
    print(SIGNING_HELP)


def _branch_conflict(name: str, taken: set[str]) -> str | None:
    """Return a branch that cannot exist beside name, such as feature beside feature/x."""
    for other in taken:
        if other == name:
            continue
        if other.startswith(name + "/") or name.startswith(other + "/"):
            return other
    return None


def _refuse_branch_conflict(name: str, conflict: str) -> None:
    """Stop before creating a local branch that git cannot store next to conflict."""
    raise SystemExit(
        f"Cannot create local branch {name}: it conflicts with {conflict}. "
        "Rename or delete one of them, then run this again."
    )


def ensure_local_branches(git: Git) -> None:
    """Create a local branch for each origin branch that does not already exist.

    Refuses before creating any branch when two names cannot coexist.
    """
    existing = set(local_branches(git))
    taken = set(existing)
    pending: list[tuple[str, str]] = []
    for ref in for_each_ref(git, "refs/remotes/origin"):
        name = ref.removeprefix("refs/remotes/origin/")
        if not name or name in existing:
            continue
        conflict = _branch_conflict(name, taken)
        if conflict:
            _refuse_branch_conflict(name, conflict)
        taken.add(name)
        pending.append((name, ref))
    for name, ref in pending:
        git.run("branch", "--", name, ref)


def materialize_local_branch(git: Git, branch: str) -> None:
    """Create branch from origin/branch when the local branch is missing.

    Does not create any other origin branch.
    """
    local = f"refs/heads/{branch}"
    if git.run("show-ref", "--verify", "--quiet", local, check=False).returncode == 0:
        return
    remote = f"refs/remotes/origin/{branch}"
    if git.run("show-ref", "--verify", "--quiet", remote, check=False).returncode != 0:
        raise SystemExit(f"No local branch named {branch}.")
    conflict = _branch_conflict(branch, set(local_branches(git)))
    if conflict:
        _refuse_branch_conflict(branch, conflict)
    git.run("branch", "--", branch, remote)


def require_clean(git: Git) -> None:
    """Stop when the worktree has uncommitted changes, so a later reset cannot discard them."""
    status = git.out("status", "--porcelain")
    if status.strip():
        raise SystemExit(
            "Cannot rewrite: the worktree has uncommitted changes. "
            "Do not commit them. Restore the last commit, then run this script again."
        )
