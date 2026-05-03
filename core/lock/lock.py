"""core/lock/lock.py — POSIX flock + 메타마커 lock 메커니즘 (BILLI ORDER msg 466 C-1·C-2, AGENTS §19.6)"""
import fcntl
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LOCK_TIMEOUT_SEC = 3600  # mtime 기반 stale safety net (flock 단독으로 거의 불필요)

# 프로세스 내부 fd 보존 (release 까지 close 금지 — flock 은 fd close 시 자동 해제)
_LOCK_FDS: dict[str, int] = {}


def _lock_path(base_dir: Path, name: str) -> Path:
    return base_dir / f".{name}.lock"


def _key(base_dir: Path, name: str) -> str:
    return f"{base_dir}::{name}"


def _try_lock(lp: Path) -> int | None:
    """fd 획득 + flock 시도. 실패 시 fd close 후 None."""
    fd = os.open(str(lp), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (OSError, BlockingIOError):
        os.close(fd)
        return None


def acquire(base_dir: Path, name: str, timeout_sec: int = LOCK_TIMEOUT_SEC) -> bool:
    """POSIX flock (LOCK_EX|LOCK_NB) 기반 host-level mutual exclusion.

    flock 의 본질:
    - 같은 host 의 다른 process 는 동시 acquire 불가 (LOCK_NB → 즉시 fail)
    - process 종료 시 fd auto-close → flock 자동 해제 (hung process 보호)
    - cross-host (Mac·VPS) 차단은 본 함수 영역 외 — ORDER 메타마커 (status: dispatched) 가 담당

    fallback:
    - mtime 이 timeout_sec 초과 → 단순 stale 판단 후 한 번 재시도 (host crash 등 극단 케이스)

    Returns: True = lock 획득. False = 다른 process 가 보유 중.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    lp = _lock_path(base_dir, name)
    k = _key(base_dir, name)

    # 같은 process 내부 재진입 허용 (idempotent)
    if k in _LOCK_FDS:
        return True

    fd = _try_lock(lp)
    if fd is None:
        # mtime stale fallback (host crash 등 매우 드문 경우)
        try:
            age = time.time() - lp.stat().st_mtime
            if age >= timeout_sec:
                fd = _try_lock(lp)
        except FileNotFoundError:
            return False
        if fd is None:
            return False

    # flock 획득 — 메타데이터 기록 (pid·timestamp·timeout)
    os.ftruncate(fd, 0)
    metadata = (
        f"pid={os.getpid()}\n"
        f"acquired_at={datetime.now(timezone.utc).isoformat()}\n"
        f"timeout_sec={timeout_sec}\n"
    )
    os.write(fd, metadata.encode())
    os.fsync(fd)
    _LOCK_FDS[k] = fd
    return True


def release(base_dir: Path, name: str) -> None:
    """flock 해제 + 파일 unlink. fd close 만으로도 flock 자동 해제됨."""
    k = _key(base_dir, name)
    fd = _LOCK_FDS.pop(k, None)
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
    lp = _lock_path(base_dir, name)
    try:
        lp.unlink()
    except FileNotFoundError:
        pass


def is_locked(base_dir: Path, name: str, timeout_sec: int = LOCK_TIMEOUT_SEC) -> bool:
    """다른 process 가 보유 중인지 검사. flock 시도 후 즉시 release."""
    lp = _lock_path(base_dir, name)
    if not lp.exists():
        return False
    try:
        fd = os.open(str(lp), os.O_RDWR)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except (OSError, BlockingIOError):
            return True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
