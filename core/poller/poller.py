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


def list_new_order_files(repo_path: Path, old_sha: str, new_sha: str,
                          orders_dir: str = "orders/") -> list[str]:
    """old_sha..new_sha 사이에 추가된 orders/ .md 파일 목록 반환.

    Designer auto-merge PR은 closed 상태이므로 open PR 필터로는 감지 불가.
    git diff --diff-filter=A 로 새로 추가된 파일만 검출 (수정·삭제 제외).
    """
    if not old_sha or not new_sha:
        return []
    r = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=A", old_sha, new_sha, "--", orders_dir],
        cwd=str(repo_path), capture_output=True, text=True
    )
    if r.returncode != 0:
        return []
    return [f for f in r.stdout.splitlines()
            if f.startswith(orders_dir) and f.endswith(".md")]


def scan_recent_order_files(repo_path: Path, orders_dir: str = "orders/",
                             lookback_sec: int = 7200) -> list[str]:
    """재시작 후 retroactive 스캔 — 최근 lookback_sec 이내 추가된 orders/*.md 반환.

    전체 디렉터리 스캔 대신 git log --since 윈도우 사용:
    - 기존 완료 orders (P0·P1 등, 며칠 전 커밋) → 창 밖 → 재실행 0건
    - 최신 orders (방금 커밋) → 창 안 → 정상 감지
    - state/ 파일 없어도 old orders 재실행 없음 (시간 기반 안전 경계)
    """
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=lookback_sec)
    since = cutoff.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    r = subprocess.run(
        ["git", "log", "--name-only", "--diff-filter=A",
         "--pretty=format:", f"--since={since}", "--", orders_dir],
        cwd=str(repo_path), capture_output=True, text=True
    )
    if r.returncode != 0:
        return []
    return sorted(set(
        f for f in r.stdout.splitlines()
        if f.startswith(orders_dir) and f.endswith(".md")
    ))


def order_targets_supporter(order_path: Path) -> bool:
    """오더 파일 본문에 '수신자: 보조자' 포함 여부 확인."""
    try:
        text = order_path.read_text(encoding="utf-8")
        return "수신자" in text and "보조자" in text
    except OSError:
        return False
