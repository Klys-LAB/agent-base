"""core/git_ops/ops.py — commit·push·PR open/close (ADR-001 D5 git_ops 모듈)"""
import subprocess
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def pull(repo: Path) -> bool:
    code, _, _ = run(["git", "pull", "--ff-only"], repo)
    return code == 0


def current_sha(repo: Path) -> str:
    _, sha, _ = run(["git", "rev-parse", "HEAD"], repo)
    return sha


def add_commit_push(repo: Path, files: list[str], message: str, branch: str) -> bool:
    run(["git", "checkout", "-B", branch], repo)
    for f in files:
        run(["git", "add", f], repo)
    code, _, _ = run(["git", "commit", "-m", message], repo)
    if code != 0:
        return False
    code, _, _ = run(["git", "push", "-u", "origin", branch], repo)
    return code == 0


def open_pr(repo: Path, title: str, body: str, head: str, base: str = "main") -> str:
    code, out, _ = run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--head", head, "--base", base],
        repo
    )
    return out if code == 0 else ""
