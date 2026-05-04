"""tests/test_lock_flock.py — ADR-005-B §4 flock 단위 테스트 (lock/lock.py)."""
import multiprocessing as mp
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.lock.lock import flock_exclusive, FlockBusy, acquire, release, is_locked


def _hold_flock(path: str, hold_sec: float) -> None:
    """Worker — hold flock for hold_sec then release."""
    with flock_exclusive(Path(path), blocking=False):
        time.sleep(hold_sec)


def test_flock_exclusive_basic_acquire_release(tmp_path):
    p = tmp_path / "test.flock"
    with flock_exclusive(p):
        assert p.exists()
    # After exit, lock released — re-acquire OK
    with flock_exclusive(p):
        pass


def test_flock_exclusive_non_blocking_busy_raises(tmp_path):
    p = tmp_path / "test.flock"
    proc = mp.Process(target=_hold_flock, args=(str(p), 1.0))
    proc.start()
    time.sleep(0.2)  # ensure child has acquired
    try:
        with pytest.raises(FlockBusy):
            with flock_exclusive(p, blocking=False):
                pass
    finally:
        proc.join(timeout=3)


def test_flock_released_after_process_exit(tmp_path):
    """OS-level flock 해제 — 프로세스 종료 시 자동 release."""
    p = tmp_path / "test.flock"
    proc = mp.Process(target=_hold_flock, args=(str(p), 0.1))
    proc.start()
    proc.join(timeout=3)
    # Now child is dead — main can acquire
    with flock_exclusive(p, blocking=False):
        pass


# ─── 기존 mtime-based lock 회귀 ────────────────────────────────────────────


def test_acquire_release_cycle(tmp_path):
    assert acquire(tmp_path, "x") is True
    assert is_locked(tmp_path, "x") is True
    # POSIX flock acquire (main 정합) 는 같은 process 재진입 idempotent — True 반환
    assert acquire(tmp_path, "x") is True
    release(tmp_path, "x")
    assert is_locked(tmp_path, "x") is False
    assert acquire(tmp_path, "x") is True
    release(tmp_path, "x")


def test_stale_lock_auto_release(tmp_path):
    lp = tmp_path / ".x.lock"
    lp.write_text("old")
    # backdate mtime by 2 hours
    old_ts = time.time() - 7200
    import os
    os.utime(lp, (old_ts, old_ts))
    # acquire 가 stale 인지·해제·재취득
    assert acquire(tmp_path, "x", timeout_sec=3600) is True
    release(tmp_path, "x")
