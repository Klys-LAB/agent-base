#!/usr/bin/env python3
"""projects/billi/agent-billi.py — BILLI agent 메인 루프.

ADR-001 D4·D6 (초판) + ADR-005-B (메타마커 dispatch 정착, 2026-05-04).

Dispatch flow (ORDER §3.2 atomic):
    1. flock_exclusive (host-local idempotency)
    2. transition pending -> dispatched + commit + push  (atomic 묶음)
    3. run_order (claude -p)
    4. transition dispatched -> done|failed + commit + push  (atomic 묶음)

ORDER source = 메타마커 단일 진실 (ORDER §3.3). 본문 텍스트·gh PR state 검색 폐기.
state/ 디렉터리 (processed-*.done) = legacy compat — 본 정착 후 신규 ORDER 는 메타마커
단독 추적, state/ 미사용. 기존 done 마커는 잔존 (해 없음).
"""
import sys
import time
import signal
from pathlib import Path

AGENT_BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_BASE))

from core.lib.config import load_config, load_secrets
from core.log.logger import info, warn, error
from core.lock.lock import flock_exclusive, FlockBusy
from core.meta_mark import read as read_meta, find_pending, is_dispatched_stale
from core.poller.poller import (
    main_head_sha, sync_repo,
    mark_dispatched_atomic, mark_terminal_atomic, release_stale_atomic,
)
from core.dispatch.dispatch import discover_pending_orders, run_order
from core.notify.telegram import send
from core.health.health import check as health_check

PROJECT = "billi"
AGENT_DIR = AGENT_BASE / "projects" / PROJECT
HOST_FLOCK = AGENT_DIR / ".agent-billi.flock"

_running = True


def _stop(sig, frame):
    global _running
    _running = False
    info(PROJECT, "main", "SIGTERM 수신 — 종료")
    sys.exit(0)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _is_supporter_target(repo_path: Path, order_file: str) -> bool:
    p = repo_path / order_file
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return False
    return "수신자" in text and "보조자" in text


def dispatch_order(
    repo_path: Path,
    order_file: str,
    cfg: dict,
    tg_token: str,
    tg_chat: str,
) -> None:
    """ORDER 1건 dispatch — atomic 메타마커 transition + run_order."""
    order_stem = Path(order_file).stem
    order_path = repo_path / order_file

    if not order_path.exists():
        warn(PROJECT, "dispatch", "오더 파일 없음", order=order_file)
        return
    if not _is_supporter_target(repo_path, order_file):
        info(PROJECT, "dispatch", "보조자 대상 아님 — 스킵", order=order_stem)
        return

    meta = read_meta(order_path)
    if meta is None:
        info(PROJECT, "dispatch", "frontmatter 없음 — 메타마커 미적용 ORDER 스킵",
             order=order_stem)
        return
    if meta.status != "pending":
        info(PROJECT, "dispatch", "status != pending — 스킵",
             order=order_stem, status=meta.status)
        return

    # 1단계: pending -> dispatched (atomic + commit + push)
    ok, err = mark_dispatched_atomic(repo_path, order_file)
    if not ok:
        info(PROJECT, "dispatch", "dispatched 전이 실패 — skip",
             order=order_stem, err=err)
        return

    info(PROJECT, "dispatch", "ORDER dispatched", order=order_stem)
    if tg_token and tg_chat:
        send(tg_token, tg_chat, f"[agent-billi] ORDER 시작: {order_stem}")

    # 2단계: run_order
    order_content = order_path.read_text(encoding="utf-8")
    prompt = (
        f"BILLI supporter ORDER 실행.\n\n"
        f"오더 파일: {order_file}\n\n"
        f"{order_content}"
    )
    try:
        code, _out = run_order(
            repo_path, prompt,
            max_turns=cfg.get("dispatch", {}).get("max_turns", 100),
            max_budget_usd=cfg.get("dispatch", {}).get("max_budget_usd", 5.0),
            allowed_tools=cfg.get("dispatch", {}).get("allowed_tools"),
        )
    except Exception as e:
        error(PROJECT, "dispatch", f"run_order 예외: {e}", order=order_stem)
        code = -1

    # 3단계: dispatched -> done|failed (atomic + commit + push)
    terminal = "done" if code == 0 else "failed"
    ok, err = mark_terminal_atomic(repo_path, order_file, terminal)
    if not ok:
        warn(PROJECT, "dispatch", "terminal 전이 실패 — 다음 cycle stale 영역",
             order=order_stem, target=terminal, err=err)

    info(PROJECT, "dispatch", f"ORDER {terminal}", order=order_stem, code=code)
    if tg_token and tg_chat:
        prefix = "" if terminal == "done" else "⚠️ "
        send(tg_token, tg_chat, f"[agent-billi] {prefix}ORDER {terminal}: {order_stem}")


def release_stale_orders(repo_path: Path, orders_dir: str, timeout_sec: int) -> None:
    """dispatched 인 ORDER 중 timeout 초과 영역 자동 release (ORDER §3.2 row 4)."""
    base = repo_path / orders_dir
    if not base.is_dir():
        return
    for p in sorted(base.glob("*.md")):
        rel = str(p.relative_to(repo_path))
        if not is_dispatched_stale(p, timeout_sec=timeout_sec):
            continue
        ok, err = release_stale_atomic(repo_path, rel, timeout_sec=timeout_sec)
        if ok:
            info(PROJECT, "stale", "stale dispatched -> pending 자동 release", order=rel)
        else:
            warn(PROJECT, "stale", "stale release 실패", order=rel, err=err)


def main():
    cfg = load_config(PROJECT)
    secrets = load_secrets(PROJECT)
    tg_token = secrets.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = secrets.get("TELEGRAM_CHAT_ID", "")
    repo_path = Path(cfg.get("repo_path", AGENT_BASE / "projects/billi/repo"))
    interval = cfg.get("poller", {}).get("interval_sec", 60)
    orders_path = cfg.get("poller", {}).get("orders_path", "orders/")
    stale_timeout = cfg.get("lock", {}).get("stale_timeout_sec", 3600)

    h = health_check()
    if not h["all_required_ok"]:
        error(PROJECT, "health", "필수 의존성 누락", **h["required"])
        sys.exit(1)

    info(PROJECT, "main", "agent-billi 시작 (ADR-005-B 메타마커 dispatch)",
         interval=interval, orders_path=orders_path, stale_timeout_sec=stale_timeout)

    last_sha = main_head_sha(repo_path)
    sync_fail_streak = 0
    SYNC_ALERT_STREAK = 5

    # First run: 동기화 후 metamarker 기반 retroactive scan (시간 윈도우 불필요)
    ok, err = sync_repo(repo_path)
    if not ok:
        warn(PROJECT, "sync", "초기 sync 실패", err=err)
    try:
        with flock_exclusive(HOST_FLOCK, blocking=False):
            release_stale_orders(repo_path, orders_path, stale_timeout)
            for order_file in discover_pending_orders(repo_path, orders_path):
                dispatch_order(repo_path, order_file, cfg, tg_token, tg_chat)
    except FlockBusy:
        info(PROJECT, "main", "다른 actor 가 host flock 보유 — 첫 cycle skip")

    while _running:
        try:
            ok, err = sync_repo(repo_path)
            if not ok:
                sync_fail_streak += 1
                warn(PROJECT, "sync", "sync_repo skip", err=err, streak=sync_fail_streak)
                if sync_fail_streak == SYNC_ALERT_STREAK and tg_token and tg_chat:
                    send(tg_token, tg_chat,
                         f"[agent-billi] ⚠️ sync_repo {SYNC_ALERT_STREAK} cycle 연속 실패 — {err}")
            else:
                if sync_fail_streak > 0:
                    info(PROJECT, "sync", "sync_repo 복구", prev_streak=sync_fail_streak)
                    sync_fail_streak = 0

                # main HEAD 변경 감지는 logging 용도로만 유지 (메타마커 단독 source).
                sha = main_head_sha(repo_path)
                if sha and sha != last_sha:
                    info(PROJECT, "poller", "main HEAD 변경 감지", sha=sha[:8])
                    last_sha = sha

                # 매 cycle 메타마커 단독 검색 — pending ORDER + stale dispatched.
                try:
                    with flock_exclusive(HOST_FLOCK, blocking=False):
                        release_stale_orders(repo_path, orders_path, stale_timeout)
                        for order_file in discover_pending_orders(repo_path, orders_path):
                            dispatch_order(repo_path, order_file, cfg, tg_token, tg_chat)
                except FlockBusy:
                    info(PROJECT, "main", "다른 actor 가 host flock 보유 — cycle skip")

        except Exception as e:
            error(PROJECT, "main", f"루프 예외: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
