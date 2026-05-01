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
from core.poller.poller import list_open_prs, main_head_sha
from core.dispatch.dispatch import claude_available, run_order
from core.notify.telegram import send
from core.health.health import check as health_check

PROJECT = "billi"
LOCK_DIR = AGENT_BASE / "projects" / PROJECT
LOCK_NAME = "agent-billi"

_running = True


def _stop(sig, frame):
    global _running
    _running = False
    release(LOCK_DIR, LOCK_NAME)
    info(PROJECT, "main", "SIGTERM 수신 — 종료")
    sys.exit(0)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def main():
    cfg = load_config(PROJECT)
    secrets = load_secrets(PROJECT)
    tg_token = secrets.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = secrets.get("TELEGRAM_CHAT_ID", "")
    repo_path = Path(cfg.get("repo_path", AGENT_BASE / "projects/billi/repo"))
    interval = cfg.get("poller", {}).get("interval_sec", 60)
    branch_prefix = cfg.get("poller", {}).get("branch_prefix", "supporter/")

    h = health_check()
    if not h["all_required_ok"]:
        error(PROJECT, "health", "필수 의존성 누락", **h["required"])
        sys.exit(1)

    info(PROJECT, "main", "agent-billi 시작", interval=interval)

    last_sha = ""
    while _running:
        try:
            sha = main_head_sha(repo_path)
            if sha and sha != last_sha:
                info(PROJECT, "poller", "main HEAD 변경 감지", sha=sha[:8])
                last_sha = sha
                prs = list_open_prs(repo_path, branch_prefix)
                for pr in prs:
                    info(PROJECT, "dispatch", "PR 감지", pr=pr["number"], branch=pr["headRefName"])
                    prompt = (
                        f"BILLI supporter ORDER: PR #{pr['number']} ({pr['headRefName']}) 처리. "
                        f"repo: {repo_path}"
                    )
                    code, out = run_order(
                        repo_path, prompt,
                        max_turns=cfg.get("dispatch", {}).get("max_turns", 100),
                        max_budget_usd=cfg.get("dispatch", {}).get("max_budget_usd", 5.0),
                        allowed_tools=cfg.get("dispatch", {}).get("allowed_tools"),
                    )
                    if tg_token and tg_chat:
                        status = "PASS" if code == 0 else "FAIL"
                        send(tg_token, tg_chat, f"[agent-billi] PR #{pr['number']} {status}")
        except Exception as e:
            error(PROJECT, "main", f"루프 예외: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
