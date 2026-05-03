"""tests/test_lock_and_meta.py — flock + order_meta 단위·시뮬레이션 검증 (PRE-P3-A)

실행:
    cd /root/Klys-LAB/agent-base
    python3 tests/test_lock_and_meta.py

기대: 모든 case PASS, exit 0.
"""
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.lock.lock import acquire, release, is_locked
from core.poller.order_meta import (
    read_meta, write_meta, mark_dispatched, mark_done, mark_failed,
    is_dispatchable, ensure_pending,
)


def _print_result(name: str, ok: bool, msg: str = "") -> None:
    icon = "PASS" if ok else "FAIL"
    suffix = f" — {msg}" if msg else ""
    print(f"  [{icon}] {name}{suffix}")


# === flock 테스트 ===

def test_flock_basic():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ok1 = acquire(d, "test1")
        # 같은 process 재진입 — idempotent
        ok2 = acquire(d, "test1")
        release(d, "test1")
        return ok1 and ok2


def _child_acquire(d_str: str, name: str, queue: mp.Queue) -> None:
    d = Path(d_str)
    # 자식 프로세스에서 acquire 시도
    result = acquire(d, name)
    queue.put(result)
    if result:
        time.sleep(2)
        release(d, name)


def test_flock_cross_process():
    """다른 process 가 보유 중일 때 동시 acquire 차단 검증."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # parent 가 lock 보유
        if not acquire(d, "exclusive"):
            return False
        # child 가 동시 acquire 시도 — False 기대
        q = mp.Queue()
        p = mp.Process(target=_child_acquire, args=(str(d), "exclusive", q))
        p.start()
        p.join(timeout=5)
        child_result = q.get_nowait()
        # parent release 후 child 재시도는 본 테스트 범위 외
        release(d, "exclusive")
        return not child_result  # child 가 False 받았으면 PASS


def test_flock_release_re_acquire():
    """release 후 재 acquire 가능."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ok1 = acquire(d, "reuse")
        release(d, "reuse")
        ok2 = acquire(d, "reuse")
        release(d, "reuse")
        return ok1 and ok2


def test_is_locked():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # 미잠금 상태
        before = is_locked(d, "checked")
        acquire(d, "checked")
        # 다른 process 에서 확인 (자기 process 는 같은 fd 재진입이라 부정확)
        # 단순 검증 — 잠금 후 lock 파일 존재
        assert (d / ".checked.lock").exists()
        release(d, "checked")
        after = is_locked(d, "checked")
        return not before and not after


# === order_meta 테스트 ===

def test_meta_read_no_front_matter():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "order.md"
        p.write_text("# ORDER X\n\nBody")
        meta = read_meta(p)
        return meta == {"status": "pending"}


def test_meta_write_create():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "order.md"
        p.write_text("# ORDER X\n\nBody")
        write_meta(p, status="pending", dispatched_at="", dispatched_pid="")
        text = p.read_text()
        meta = read_meta(p)
        return meta.get("status") == "pending" and text.startswith("---\n")


def test_meta_dispatch_done():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "order.md"
        p.write_text("# ORDER X\n\nBody")
        write_meta(p, status="pending", dispatched_at="", dispatched_pid="")
        mark_dispatched(p)
        meta = read_meta(p)
        if meta.get("status") != "dispatched":
            return False
        if not meta.get("dispatched_at"):
            return False
        mark_done(p)
        meta2 = read_meta(p)
        return meta2.get("status") == "done"


def test_is_dispatchable():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "order.md"
        p.write_text("# ORDER X\n\nBody")
        ensure_pending(p)
        if not is_dispatchable(p):
            return False
        mark_dispatched(p)
        if is_dispatchable(p):
            return False
        mark_failed(p)
        return not is_dispatchable(p)


def test_meta_invalid_status():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "order.md"
        p.write_text("# ORDER X")
        try:
            write_meta(p, status="invalid_status")
            return False
        except ValueError:
            return True


def test_meta_preserve_body():
    """front matter 갱신 시 body 내용 보존."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "order.md"
        body = "# ORDER X\n\nLine 1\nLine 2\n"
        p.write_text(body)
        write_meta(p, status="pending")
        text = p.read_text()
        return body.strip() in text


# === 시뮬레이션: 동시 dispatch 시나리오 ===

def _simulate_dispatch(d_str: str, order_path_str: str, queue: mp.Queue) -> None:
    """dispatch 시뮬: meta 검사 + flock + body 작업 + meta 갱신."""
    d = Path(d_str)
    order_path = Path(order_path_str)
    pid = os.getpid()

    # idempotency check (cross-host 상응)
    if not is_dispatchable(order_path):
        queue.put(("skip-meta", pid))
        return

    # flock (host-level)
    if not acquire(d, f"order-{order_path.stem}"):
        queue.put(("skip-flock", pid))
        return

    try:
        mark_dispatched(order_path, pid=pid)
        time.sleep(0.5)  # body work 시뮬
        mark_done(order_path)
        queue.put(("done", pid))
    finally:
        release(d, f"order-{order_path.stem}")


def test_simulate_concurrent_dispatch():
    """동일 ORDER 에 두 process 동시 dispatch — 한쪽만 done, 다른 쪽 skip."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        order_path = d / "TEST-ORDER.md"
        order_path.write_text("# TEST ORDER\n\n수신자: 보조자")
        ensure_pending(order_path)

        q = mp.Queue()
        p1 = mp.Process(target=_simulate_dispatch, args=(str(d), str(order_path), q))
        p2 = mp.Process(target=_simulate_dispatch, args=(str(d), str(order_path), q))
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        results = []
        while not q.empty():
            results.append(q.get_nowait())

        done = [r for r in results if r[0] == "done"]
        skipped = [r for r in results if r[0] in ("skip-meta", "skip-flock")]

        # 정확히 1개 done + 1개 skip
        if len(done) != 1 or len(skipped) != 1:
            print(f"    DEBUG results: {results}")
            return False

        # 메타마커 최종 status: done
        meta = read_meta(order_path)
        return meta.get("status") == "done"


# === 메인 runner ===

def main():
    print("=== PRE-P3-A flock + meta 검증 ===")
    print()

    print("[1] flock 단위 테스트")
    cases = [
        ("flock_basic — 같은 process 재진입", test_flock_basic),
        ("flock_cross_process — 다른 process 동시 acquire 차단", test_flock_cross_process),
        ("flock_release_reuse — release 후 재 acquire", test_flock_release_re_acquire),
        ("is_locked — 잠금·해제 상태 검사", test_is_locked),
    ]
    for name, fn in cases:
        try:
            ok = fn()
        except Exception as e:
            ok = False
            _print_result(name, False, f"EXCEPTION: {type(e).__name__}: {e}")
            continue
        _print_result(name, ok)

    print()
    print("[2] order_meta 단위 테스트")
    cases = [
        ("read_no_front_matter — 없으면 implicit pending", test_meta_read_no_front_matter),
        ("write_create — front matter 신설", test_meta_write_create),
        ("dispatch·done 전이", test_meta_dispatch_done),
        ("is_dispatchable — pending 만 True", test_is_dispatchable),
        ("invalid_status ValueError", test_meta_invalid_status),
        ("preserve_body — body 보존", test_meta_preserve_body),
    ]
    for name, fn in cases:
        try:
            ok = fn()
        except Exception as e:
            ok = False
            _print_result(name, False, f"EXCEPTION: {type(e).__name__}: {e}")
            continue
        _print_result(name, ok)

    print()
    print("[3] 동시 dispatch 시뮬레이션 (multiprocessing)")
    try:
        ok = test_simulate_concurrent_dispatch()
        _print_result("concurrent_dispatch — 1 done + 1 skip", ok)
    except Exception as e:
        _print_result("concurrent_dispatch", False, f"EXCEPTION: {type(e).__name__}: {e}")
        ok = False

    print()
    print("=== 검증 종료 ===")


if __name__ == "__main__":
    main()
