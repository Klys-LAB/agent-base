#!/usr/bin/env python3
"""projects/billi/agent-billi.py — BILLI agent 메인 루프 (ADR-001 D4 D6)"""
import sys
import time
import signal
from pathlib import Path

AGENT_BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_BASE))

from core.lib.config import load_config, load_secrets
from core.log.logger import info, warn, error
from core.lock.lock import acquire, release, is_locked
from core.poller.poller import (
    list_new_order_files, scan_recent_order_files,
    order_targets_supporter, main_head_sha, sync_repo,
)
from core.poller.order_meta import (
    read_meta, mark_dispatched, mark_done, mark_failed, is_dispatchable,
)
from core.dispatch.dispatch import claude_available, run_order
from core.notify.telegram import send
from core.health.health import check as health_check

PROJECT = "billi"
LOCK_DIR = AGENT_BASE / "projects" / PROJECT
LOCK_NAME = "agent-billi"
STATE_DIR = LOCK_DIR / "state"

_running = True


def _stop(sig, frame):
    global _running
    _running = False
    release(LOCK_DIR, LOCK_NAME)
    info(PROJECT, "main", "SIGTERM 수신 — 종료")
    sys.exit(0)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def is_order_processed(order_stem: str) -> bool:
    return (STATE_DIR / f"processed-{order_stem}.done").exists()


def mark_order_processed(order_stem: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"processed-{order_stem}.done").write_text("done")


def dispatch_order(repo_path: Path, order_file: str, cfg: dict,
                   tg_token: str, tg_chat: str) -> None:
    order_stem = Path(order_file).stem
    order_path = repo_path / order_file

    if not order_path.exists():
        warn(PROJECT, "dispatch", "오더 파일 없음", order=order_file)
        return
    if not order_targets_supporter(order_path):
        info(PROJECT, "dispatch", "보조자 대상 아님 — 스킵", order=order_stem)
        return

    # ORDER 메타마커 idempotency (cross-host: Mac·VPS 동시 dispatch 차단)
    # AGENTS §19.6 + ORDER msg 466 C-2 정합
    meta = read_meta(order_path)
    status = meta.get("status", "pending")
    if status != "pending":
        info(PROJECT, "dispatch", f"메타마커 status={status} — 스킵", order=order_stem)
        return

    # GATE 검사 — [GATE] user 또는 domain 은 자동 dispatch skip (AGENTS §20)
    gate = meta.get("gate", "auto")
    if gate == "user":
        info(PROJECT, "dispatch", "[GATE] user — 사용자 처리 영역, 스킵", order=order_stem)
        return

    if is_order_processed(order_stem):
        info(PROJECT, "dispatch", "이미 처리됨 (state) — 스킵", order=order_stem)
        return

    # POSIX flock — same-host mutual exclusion (AGENTS §19.6)
    lock_key = f"order-{order_stem}"
    if not acquire(LOCK_DIR, lock_key, timeout_sec=7200):
        info(PROJECT, "dispatch", "처리 중 (flock) — 스킵", order=order_stem)
        return

    # 메타마커 dispatched 갱신 (cross-host idempotency 발효)
    try:
        mark_dispatched(order_path)
    except Exception as e:
        warn(PROJECT, "dispatch", f"메타마커 dispatched 갱신 실패: {e}", order=order_stem)
        # flock 은 이미 보유 — 계속 진행 (skip 정도의 critical 실패 아님)

    info(PROJECT, "dispatch", "ORDER 감지·실행 시작", order=order_stem)
    if tg_token and tg_chat:
        send(tg_token, tg_chat, f"[agent-billi] ORDER 시작: {order_stem}")

    order_content = order_path.read_text(encoding="utf-8")
    prompt = (
        f"BILLI supporter ORDER 실행.\n\n"
        f"오더 파일: {order_file}\n\n"
        f"{order_content}"
    )
    code, out = run_order(
        repo_path, prompt,
        max_turns=cfg.get("dispatch", {}).get("max_turns", 100),
        max_budget_usd=cfg.get("dispatch", {}).get("max_budget_usd", 5.0),
        allowed_tools=cfg.get("dispatch", {}).get("allowed_tools"),
    )

    mark_order_processed(order_stem)
    # 메타마커 종료 상태
    try:
        if code == 0:
            mark_done(order_path)
        else:
            mark_failed(order_path)
    except Exception as e:
        warn(PROJECT, "dispatch", f"메타마커 종료 갱신 실패: {e}", order=order_stem, code=code)

    release(LOCK_DIR, lock_key)

    status_str = "PASS" if code == 0 else "FAIL"
    info(PROJECT, "dispatch", f"ORDER {status_str}", order=order_stem, code=code)
    if tg_token and tg_chat:
        send(tg_token, tg_chat, f"[agent-billi] ORDER {status_str}: {order_stem}")


def main():
    cfg = load_config(PROJECT)
    secrets = load_secrets(PROJECT)
    tg_token = secrets.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = secrets.get("TELEGRAM_CHAT_ID", "")
    repo_path = Path(cfg.get("repo_path", AGENT_BASE / "projects/billi/repo"))
    interval = cfg.get("poller", {}).get("interval_sec", 60)
    orders_path = cfg.get("poller", {}).get("orders_path", "orders/")

    h = health_check()
    if not h["all_required_ok"]:
        error(PROJECT, "health", "필수 의존성 누락", **h["required"])
        sys.exit(1)

    lookback = cfg.get("poller", {}).get("retroactive_lookback_sec", 7200)
    info(PROJECT, "main", "agent-billi 시작", interval=interval,
         orders_path=orders_path, retroactive_lookback_sec=lookback)

    # First run: 동기화 후 retroactive scan
    # - sync_repo: fetch + ff-only pull (BILLI msg 449, list_new_order_files 의존성)
    # - scan_recent_order_files: state/ 비어도 lookback 윈도우로 안전 경계
    ok, err = sync_repo(repo_path)
    if not ok:
        warn(PROJECT, "sync", "초기 sync 실패 — retroactive 스캔 미실행", err=err)
    else:
        for order_file in scan_recent_order_files(repo_path, orders_path, lookback):
            if not is_order_processed(Path(order_file).stem):
                dispatch_order(repo_path, order_file, cfg, tg_token, tg_chat)

    last_sha = main_head_sha(repo_path)
    sync_fail_streak = 0
    SYNC_ALERT_STREAK = 5  # 5 cycle (5 분) 연속 실패 시 1회 Telegram 알림
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

                sha = main_head_sha(repo_path)
                if sha and sha != last_sha:
                    info(PROJECT, "poller", "main HEAD 변경 감지", sha=sha[:8])
                    new_orders = list_new_order_files(repo_path, last_sha, sha, orders_path)
                    last_sha = sha
                    for order_file in new_orders:
                        dispatch_order(repo_path, order_file, cfg, tg_token, tg_chat)
        except Exception as e:
            error(PROJECT, "main", f"루프 예외: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
