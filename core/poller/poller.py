"""core/poller/poller.py — GitHub PR state 폴링·orders 감지 (ADR-001 D5 poller 모듈)"""
import json
import subprocess
from pathlib import Path


def gh(args: list[str], cwd: Path) -> tuple[int, str]:
    r = subprocess.run(["gh"] + args, cwd=str(cwd), capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def list_open_prs(repo_path: Path, branch_prefix: str) -> list[dict]:
    code, out = gh(
        ["pr", "list", "--json", "number,headRefName,title,state",
         "--state", "open", "--limit", "20"],
        repo_path
    )
    if code != 0 or not out:
        return []
    prs = json.loads(out)
    return [p for p in prs if p["headRefName"].startswith(branch_prefix)]


def get_pr_files(repo_path: Path, pr_number: int) -> list[str]:
    code, out = gh(["pr", "diff", str(pr_number), "--name-only"], repo_path)
    if code != 0:
        return []
    return [f for f in out.splitlines() if f]


def main_head_sha(repo_path: Path) -> str:
    r = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=str(repo_path), capture_output=True, text=True
    )
    if r.returncode != 0 or not r.stdout:
        return ""
    return r.stdout.split()[0]
