"""core/poller/poller.py — GitHub PR state 폴링·orders 감지 (ADR-001 D5 poller 모듈)"""
import json
import subprocess
import time
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


def sync_repo(repo_path: Path) -> tuple[bool, str]:
    """git fetch + ff-only pull origin main. 매 cycle 호출 (BILLI msg 449).

    이전 버그 — list_new_order_files 가 git diff old_sha new_sha 를 사용하지만
    fetch 누락 시 new_sha 가 local objects 에 없어 diff 가 빈 결과 반환.
    P2-003-R1 (8a73d43, 6h+ 무감지) 직접 원인.

    정책:
    - working tree dirty → skip (False, "dirty"). 자동 stash 금지.
    - fetch 실패 (네트워크) → skip (False, "fetch fail"). 다음 cycle 재시도.
    - ff-only 실패 (local 분기·conflict) → skip (False, "non-ff"). force pull 금지.
    - 모든 실패 시 last_sha 미갱신 → 다음 cycle 정상 복구되면 자연 catch up.

    Returns: (ok, error_msg). ok=True 시 error_msg="" + local main = origin/main.
    """
    # 1. dirty check — uncommitted changes 보호
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_path), capture_output=True, text=True, timeout=10
    )
    if r.returncode != 0:
        return False, f"git status fail: {r.stderr.strip()[:120]}"
    if r.stdout.strip():
        n = len(r.stdout.splitlines())
        return False, f"working tree dirty ({n} files) — manual cleanup 필요"

    # 2. fetch origin
    r = subprocess.run(
        ["git", "fetch", "origin", "main"],
        cwd=str(repo_path), capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        return False, f"git fetch fail: {r.stderr.strip()[:200]}"

    # 3. ff-only pull (force pull 금지)
    r = subprocess.run(
        ["git", "pull", "--ff-only", "origin", "main"],
        cwd=str(repo_path), capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        return False, f"git pull --ff-only fail (local 분기·conflict 가능): {r.stderr.strip()[:200]}"

    return True, ""


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


def scan_pending_orders(repo_path: Path, orders_dir: str = "orders/") -> list[str]:
    """orders/ 디렉터리 전체 scan — frontmatter status: pending 인 .md 파일 반환.

    AGENTS §19.6 frontmatter 단일 진실 정합 (BILLI msg 590 root cause fix).
    git diff filter 의존 폐기 — added/modified/순서 무관.

    이전 패턴 (list_new_order_files + --diff-filter=A) 의 root cause:
    - added 만 catch — modification (갱신본 ORDER) skip
    - PRE-P3-B-R2 (msg 588) 갱신본 dispatch 영역 0 (BILLI PR #176)
    - baseline (S-007·S-008·ADR-005-B) added 패턴 정합 영역만 통과

    본 함수 영역:
    - orders/ 전체 scan (.md 파일)
    - frontmatter status: pending 만 반환 (is_dispatchable 호출)
    - is_order_processed 체크는 호출자 책임 (state/processed-*.done)

    Returns: orders/<filename>.md 형식 list (정렬, idempotent).
    """
    from core.poller.order_meta import is_dispatchable

    od = repo_path / orders_dir
    if not od.is_dir():
        return []

    prefix = orders_dir.rstrip("/")
    result = []
    for p in sorted(od.glob("*.md")):
        if is_dispatchable(p):
            result.append(f"{prefix}/{p.name}")
    return result


# ─── ADR-005-B 메타마커 dispatch 영역 ────────────────────────────────────
#
# atomic transition = 메타마커 갱신 → git add → commit → push 한 묶음.
# 실패 시 retry (max 3회), 모두 실패하면 다음 cycle stale 감지로 자연 회복.
#
# 메시지 brand 형식 (ORDER §3.4):
#   meta(ADR-005-B): orders/<id>.md status: <from> -> <to>


def _git(repo_path: Path, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    r = subprocess.run(
        ["git"] + args,
        cwd=str(repo_path), capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def commit_and_push_meta(
    repo_path: Path,
    order_file: str,
    from_status: str,
    to_status: str,
    branch: str = "main",
    retries: int = 3,
) -> tuple[bool, str]:
    """git add <order_file> + commit + push origin <branch>. atomic 묶음.

    각 retry 사이 짧은 backoff. 모두 실패 시 (False, error_msg). 호출 측은
    메타마커가 file 에는 반영되었지만 push 가 누락된 partial state 를 인식해야 함
    — 다음 cycle 의 stale 감지 (is_dispatched_stale) 또는 git 동기화 (sync_repo)
    가 자연 복구 path.

    ORDER §3.4 brand: meta(ADR-005-B): orders/<id>.md status: <from> -> <to>
    """
    msg = f"meta(ADR-005-B): {order_file} status: {from_status} -> {to_status}"
    last_err = ""
    for attempt in range(1, retries + 1):
        code, _, err = _git(repo_path, ["add", "--", order_file])
        if code != 0:
            last_err = f"git add fail: {err[:200]}"
            time.sleep(0.5 * attempt)
            continue
        code, _, err = _git(repo_path, ["commit", "-m", msg])
        if code != 0:
            # nothing to commit (메타마커가 이미 같은 상태) → 성공으로 취급
            if "nothing to commit" in err.lower() or "nothing added" in err.lower():
                return True, ""
            last_err = f"git commit fail: {err[:200]}"
            time.sleep(0.5 * attempt)
            continue
        code, _, err = _git(repo_path, ["push", "origin", branch], timeout=60)
        if code != 0:
            last_err = f"git push fail: {err[:200]}"
            time.sleep(0.5 * attempt)
            continue
        return True, ""
    return False, last_err


def mark_dispatched_atomic(
    repo_path: Path,
    order_file: str,
    pid: int | None = None,
) -> tuple[bool, str]:
    """pending -> dispatched + commit + push (atomic 묶음).

    Returns (ok, error_msg). ok=False 시 호출 측은 dispatch skip — 다른 actor 가
    선점했거나 git push 실패. partial state (file 변경됐으나 push 실패) 는
    다음 sync_repo 에서 해소.
    """
    from core.meta_mark import transition  # 순환 import 회피

    order_path = repo_path / order_file
    ok, _ = transition(order_path, "pending", "dispatched", pid=pid)
    if not ok:
        return False, "transition failed (status != pending)"
    return commit_and_push_meta(repo_path, order_file, "pending", "dispatched")


def mark_terminal_atomic(
    repo_path: Path,
    order_file: str,
    to_status: str,  # "done" | "failed"
) -> tuple[bool, str]:
    """dispatched -> done|failed + commit + push."""
    from core.meta_mark import transition

    if to_status not in ("done", "failed"):
        return False, f"invalid terminal status: {to_status}"
    order_path = repo_path / order_file
    ok, _ = transition(order_path, "dispatched", to_status)
    if not ok:
        return False, f"transition failed (status != dispatched, target={to_status})"
    return commit_and_push_meta(repo_path, order_file, "dispatched", to_status)


def release_stale_atomic(
    repo_path: Path,
    order_file: str,
    timeout_sec: int = 3600,
) -> tuple[bool, str]:
    """stale dispatched -> pending (자동 release).

    is_dispatched_stale True 일 때만 transition. dispatched_at·dispatched_pid clear.
    다음 cycle 에서 자연 재dispatch.
    """
    from core.meta_mark import transition, is_dispatched_stale

    order_path = repo_path / order_file
    if not is_dispatched_stale(order_path, timeout_sec=timeout_sec):
        return False, "not stale"
    ok, _ = transition(order_path, "dispatched", "pending")
    if not ok:
        return False, "transition failed (status != dispatched)"
    return commit_and_push_meta(repo_path, order_file, "dispatched", "pending")
