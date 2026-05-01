"""core/lock/lock.py — idempotency·timeout·재시도 (ADR-001 D5 lock 모듈)"""
import time
from pathlib import Path
from datetime import datetime, timezone


LOCK_TIMEOUT_SEC = 3600  # 1시간 기본 timeout


def _lock_path(base_dir: Path, name: str) -> Path:
    return base_dir / f".{name}.lock"


def acquire(base_dir: Path, name: str, timeout_sec: int = LOCK_TIMEOUT_SEC) -> bool:
    lp = _lock_path(base_dir, name)
    if lp.exists():
        age = time.time() - lp.stat().st_mtime
        if age < timeout_sec:
            return False  # 이미 보유
        lp.unlink()  # stale lock 해제
    lp.write_text(datetime.now(timezone.utc).isoformat())
    return True


def release(base_dir: Path, name: str) -> None:
    lp = _lock_path(base_dir, name)
    if lp.exists():
        lp.unlink()


def is_locked(base_dir: Path, name: str, timeout_sec: int = LOCK_TIMEOUT_SEC) -> bool:
    lp = _lock_path(base_dir, name)
    if not lp.exists():
        return False
    age = time.time() - lp.stat().st_mtime
    return age < timeout_sec
