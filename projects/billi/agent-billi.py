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
    order_targets_supporter, main_head_sha,
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
    if is_order_processed(order_stem):
        info(PROJECT, "dispatch", "이미 처리됨 — 스킵", order=order_stem)
        return

    lock_key = f"order-{order_stem}"
    if not acquire(LOCK_DIR, lock_key, timeout_sec=7200):
        info(PROJECT, "dispatch", "처리 중 (lock) — 스킵", order=order_stem)
        return

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
    release(LOCK_DIR, lock_key)

    status = "PASS" if code == 0 else "FAIL"
    info(PROJECT, "dispatch", f"ORDER {status}", order=order_stem, code=code)
    if tg_token and tg_chat:
        send(tg_token, tg_chat, f"[agent-billi] ORDER {status}: {order_stem}")


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

    # First run: retroactive scan — 최근 lookback_sec 이내 orders만 감지
    # (전체 스캔 금지: state/ 비어있을 때 기존 orders 전부 재실행되는 버그 방지)
    for order_file in scan_recent_order_files(repo_path, orders_path, lookback):
        if not is_order_processed(Path(order_file).stem):
            dispatch_order(repo_path, order_file, cfg, tg_token, tg_chat)

    last_sha = main_head_sha(repo_path)
    while _running:
        try:
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
