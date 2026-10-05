"""Command line for git-dropper-cleanup.

Does not run Node, npm, or any file from the target repository, and does not change git config.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import traceback
from pathlib import Path

from git_dropper_cleanup.env import omitted_target
from git_dropper_cleanup.gitio import Git, resolve_targets, signing_key
from git_dropper_cleanup.md_report import write_error_report
from git_dropper_cleanup.push import push_repo, was_rewritten
from git_dropper_cleanup.report import check_repo
from git_dropper_cleanup.rewrite import branches_repo, fix_repo, rewrite_repo


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse operator flags. Only one of check, fix, branches, or rewrite is accepted."""
    parser = argparse.ArgumentParser(
        description="Aftermath cleanup: remove an appended JavaScript dropper from a git repository without running its code."
    )
    parser.add_argument("paths", nargs="*", help="Git URL or repo path")
    parser.add_argument("--check", action="store_true", help="Report clean branches and affected commits. This is the default.")
    parser.add_argument("--fix", action="store_true", help="Clean the current checkout. No commit.")
    parser.add_argument("--branches", action="store_true", help="Clean every local branch tip and commit when a signing key exists.")
    parser.add_argument("--rewrite", action="store_true", help="Rewrite infected commits and their descendants.")
    parser.add_argument("--branch", help="Rewrite or push only this local branch.")
    parser.add_argument("--push", action="store_true", help="Push after review. Uses --force-with-lease after a rewrite.")
    parser.add_argument(
        "--push-main",
        action="store_true",
        help="Allow a rewritten main or master to be force-pushed.",
    )
    parser.add_argument(
        "--all-in-dir",
        action="store_true",
        help="Treat a parent folder as a list of clones.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write markdown reports under reports/<repo>/ in the tool checkout.",
    )
    args = parser.parse_args(argv)
    chosen = [name for name, flag in (
        ("--check", args.check),
        ("--fix", args.fix),
        ("--branches", args.branches),
        ("--rewrite", args.rewrite),
    ) if flag]
    if len(chosen) > 1:
        parser.error("Pass only one of --check, --fix, --branches, or --rewrite.")
    if args.branch and not (args.rewrite or (args.push and not chosen)):
        parser.error("--branch is only combined with --rewrite, or with --push after a rewrite.")
    if args.push and chosen and chosen[0] not in ("--branches", "--rewrite"):
        parser.error("--push is only combined with --branches or --rewrite, or used on its own after a rewrite.")
    return args


def effective_paths(paths: list[str]) -> list[str]:
    """Return CLI paths, or REPO_URL / DEMO_REPO from the environment when omitted."""
    if paths:
        return paths
    target = omitted_target()
    if target:
        return [target]
    raise SystemExit(
        "Pass a git URL or a repo path, or set REPO_URL (or DEMO_REPO) in the environment. See README.md."
    )


def selected_mode(args: argparse.Namespace) -> str:
    """Return the one action this invocation will run."""
    if args.rewrite:
        return "rewrite"
    if args.branches:
        return "branches"
    if args.fix:
        return "fix"
    if args.push:
        return "push"
    return "check"


def _run(argv: list[str]) -> int:
    """Run check, fix, branch-tip cleanup, rewrite, or push for each selected repo."""
    args = parse_args(argv)
    hooks = Path(tempfile.mkdtemp(prefix="git-dropper-cleanup-hooks-"))
    targets = resolve_targets(effective_paths(args.paths), args.all_in_dir, hooks)
    mode = selected_mode(args)
    write_report = not args.no_report
    status = 0
    for repo in targets:
        git = Git(repo, hooks)
        if mode == "check":
            status = max(status, check_repo(git, write_report=write_report))
        elif mode == "fix":
            fix_repo(git)
        elif mode == "branches":
            sign = bool(signing_key(git))
            branches_repo(git, sign)
            if args.push and sign:
                status = max(status, push_repo(
                    git,
                    args.push_main,
                    rewritten=False,
                    write_report=write_report,
                ))
            elif args.push:
                print("Skipped push because nothing was committed.")
        elif mode == "rewrite":
            sign = bool(signing_key(git))
            rewrite_repo(git, sign, branch=args.branch, write_report=write_report)
            if args.push:
                status = max(status, push_repo(
                    git,
                    args.push_main,
                    rewritten=True,
                    only_branch=args.branch,
                    write_report=write_report,
                ))
        elif mode == "push":
            status = max(status, push_repo(
                git,
                args.push_main,
                rewritten=was_rewritten(git),
                only_branch=args.branch,
                write_report=write_report,
            ))
    return status


def _requested_mode(argv: list[str]) -> str:
    """Return a useful operation label even when argument parsing fails."""
    for flag, mode in (
        ("--rewrite", "rewrite"),
        ("--branches", "branches"),
        ("--fix", "fix"),
        ("--push", "push"),
        ("--check", "check"),
    ):
        if flag in argv:
            return mode
    return "check"


def main(argv: list[str] | None = None) -> int:
    """Run the command and persist diagnostics for every fatal error."""
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        return _run(raw)
    except (SystemExit, Exception) as error:
        successful_exit = isinstance(error, SystemExit) and error.code in (None, 0)
        if not successful_exit and "--no-report" not in raw:
            try:
                path = write_error_report(
                    error=error,
                    argv=raw,
                    mode=_requested_mode(raw),
                    traceback_text=traceback.format_exc(),
                )
                print(f"Error report written: {path}", file=sys.stderr)
            except Exception as logging_error:
                print(f"Could not write error report: {logging_error}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.exit(main())
