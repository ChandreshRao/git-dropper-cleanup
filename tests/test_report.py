"""Low-memory history scan and subprocess diagnostics."""

from pathlib import Path
import subprocess

from git_dropper_cleanup.gitio import command_failure
from git_dropper_cleanup.report import CODE_PATHSPECS, GREP_BATCH, grep_commits


class FakeGit:
    """Record git arguments without starting a subprocess."""

    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        self.repo = Path("/sample")
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def run(self, *args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return self.result


def test_grep_uses_small_single_thread_code_only_batches() -> None:
    git = FakeGit(subprocess.CompletedProcess([], 1, "", ""))
    commits = [f"{number:040x}" for number in range(GREP_BATCH + 1)]
    assert grep_commits(git, commits) == []
    assert len(git.calls) == 2
    for call in git.calls:
        assert call[:3] == ("-c", "grep.threads=1", "grep")
        assert "--" in call
        assert call[call.index("--") + 1 :] == CODE_PATHSPECS


def test_signal_failure_has_name_and_empty_output_hint() -> None:
    detail = command_failure(-9, "")
    assert "exit -9 (SIGKILL)" in detail
    assert "killed by the operating system" in detail
