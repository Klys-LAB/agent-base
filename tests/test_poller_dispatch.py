"""tests/test_poller_dispatch.py — scan_pending_orders 단위 테스트 (BILLI msg 590 fix)

목적:
    AGENTS §19.6 frontmatter 단일 진실 정합 검증.
    이전 패턴 (list_new_order_files + --diff-filter=A) 의 root cause —
    modification (갱신본 ORDER) skip — 본 fix 영역 자연 catch 검증.

실행:
    cd /root/Klys-LAB/agent-base
    python3 tests/test_poller_dispatch.py

기대: 모든 case PASS, exit 0.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.poller.poller import scan_pending_orders
from core.poller.order_meta import (
    write_meta, mark_dispatched, mark_done, mark_failed, ensure_pending,
)


def _print_result(name: str, ok: bool, msg: str = "") -> None:
    icon = "PASS" if ok else "FAIL"
    suffix = f" — {msg}" if msg else ""
    print(f"  [{icon}] {name}{suffix}")


def _setup_repo(td: Path) -> Path:
    """tmp orders/ 디렉터리 생성."""
    od = td / "orders"
    od.mkdir(parents=True, exist_ok=True)
    return od


def test_scan_empty_dir():
    """orders/ 디렉터리 없으면 빈 list."""
    with tempfile.TemporaryDirectory() as td:
        result = scan_pending_orders(Path(td))
        return result == []


def test_scan_no_md_files():
    """orders/ 디렉터리 비었으면 빈 list."""
    with tempfile.TemporaryDirectory() as td:
        _setup_repo(Path(td))
        return scan_pending_orders(Path(td)) == []


def test_scan_pending_added():
    """status: pending 인 신규 ORDER catch."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)
        p = od / "ORDER-A.md"
        p.write_text("# ORDER A\n\n수신자: 보조자\n")
        ensure_pending(p)

        result = scan_pending_orders(repo)
        return result == ["orders/ORDER-A.md"]


def test_scan_pending_modified():
    """기존 ORDER 갱신본 (modification) catch — root cause fix 핵심.

    이전 패턴 (--diff-filter=A) 은 modification skip → BILLI PR #176 dispatch 0.
    본 영역 — frontmatter status: pending 만 보면 됨, 패턴 무관.
    """
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)
        p = od / "ORDER-B.md"
        # 1차: 신규 작성
        p.write_text("# ORDER B v1\n\n수신자: 보조자\n")
        ensure_pending(p)
        # 2차: 갱신본 (modification) — frontmatter 유지 (status: pending)
        p.write_text(p.read_text() + "\n## SCOPE 추가 영역\n")

        # 본 fix — modification 도 catch
        result = scan_pending_orders(repo)
        return result == ["orders/ORDER-B.md"]


def test_scan_skips_dispatched():
    """status: dispatched 영역 skip."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)
        p = od / "ORDER-C.md"
        p.write_text("# ORDER C\n\n수신자: 보조자\n")
        ensure_pending(p)
        mark_dispatched(p)

        result = scan_pending_orders(repo)
        return result == []


def test_scan_skips_done():
    """status: done 영역 skip."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)
        p = od / "ORDER-D.md"
        p.write_text("# ORDER D\n\n수신자: 보조자\n")
        ensure_pending(p)
        mark_done(p)

        result = scan_pending_orders(repo)
        return result == []


def test_scan_skips_failed():
    """status: failed 영역 skip."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)
        p = od / "ORDER-E.md"
        p.write_text("# ORDER E\n\n수신자: 보조자\n")
        ensure_pending(p)
        mark_failed(p)

        result = scan_pending_orders(repo)
        return result == []


def test_scan_mixed_status():
    """여러 ORDER 영역 — pending 만 catch, dispatched·done·failed skip."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)

        # pending 2건
        for name in ["ORDER-P1.md", "ORDER-P2.md"]:
            p = od / name
            p.write_text(f"# {name}\n\n수신자: 보조자\n")
            ensure_pending(p)

        # dispatched 1건
        p = od / "ORDER-D1.md"
        p.write_text("# ORDER-D1\n\n수신자: 보조자\n")
        ensure_pending(p)
        mark_dispatched(p)

        # done 1건
        p = od / "ORDER-DO1.md"
        p.write_text("# ORDER-DO1\n\n수신자: 보조자\n")
        ensure_pending(p)
        mark_done(p)

        # failed 1건
        p = od / "ORDER-F1.md"
        p.write_text("# ORDER-F1\n\n수신자: 보조자\n")
        ensure_pending(p)
        mark_failed(p)

        result = scan_pending_orders(repo)
        # pending 2건만 (정렬)
        return result == ["orders/ORDER-P1.md", "orders/ORDER-P2.md"]


def test_scan_implicit_pending():
    """frontmatter 없으면 implicit pending — catch 영역."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)
        p = od / "ORDER-NF.md"
        # frontmatter 없이 작성 — read_meta 가 implicit pending 반환
        p.write_text("# ORDER NF\n\n본문 영역\n수신자: 보조자\n")

        result = scan_pending_orders(repo)
        return result == ["orders/ORDER-NF.md"]


def test_scan_blocked_skips():
    """status: blocked 영역 skip ([GATE] user 또는 외부 차단)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)
        p = od / "ORDER-BLK.md"
        p.write_text("# ORDER BLK\n\n수신자: 보조자\n")
        ensure_pending(p)
        write_meta(p, status="blocked")

        result = scan_pending_orders(repo)
        return result == []


def test_scan_root_cause_baseline_vs_msg588():
    """msg 590 root cause 영역 baseline 비교 — added 와 modified 모두 catch.

    baseline (S-007 패턴): added → 통과 (이전 패턴도 정합)
    msg 588 (PR #176): modified → 본 fix 영역 통과 (이전 패턴 영역 0)
    """
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        od = _setup_repo(repo)

        # baseline 패턴 — added (신규 작성, 1회)
        p_added = od / "ORDER-baseline-added.md"
        p_added.write_text("# baseline added\n\n수신자: 보조자\n")
        ensure_pending(p_added)

        # msg 588 패턴 — added 후 modified (갱신본)
        p_mod = od / "ORDER-msg588-modified.md"
        p_mod.write_text("# msg 588 v1\n\n수신자: 보조자\n")
        ensure_pending(p_mod)
        # 갱신 (modification, frontmatter status: pending 유지)
        p_mod.write_text(p_mod.read_text() + "\n## 갱신 영역\n")

        result = scan_pending_orders(repo)
        # 두 패턴 모두 catch — root cause fix 정착
        return sorted(result) == [
            "orders/ORDER-baseline-added.md",
            "orders/ORDER-msg588-modified.md",
        ]


# === 메인 runner ===

def main():
    print("=== msg 590 root cause fix 검증 (scan_pending_orders) ===")
    print()

    cases = [
        ("scan_empty_dir — orders/ 없음 → 빈 list", test_scan_empty_dir),
        ("scan_no_md_files — orders/ 비었음 → 빈 list", test_scan_no_md_files),
        ("scan_pending_added — 신규 ORDER catch", test_scan_pending_added),
        ("scan_pending_modified — 갱신본 ORDER catch (root cause fix 핵심)",
         test_scan_pending_modified),
        ("scan_skips_dispatched — status: dispatched skip", test_scan_skips_dispatched),
        ("scan_skips_done — status: done skip", test_scan_skips_done),
        ("scan_skips_failed — status: failed skip", test_scan_skips_failed),
        ("scan_mixed_status — pending 만 catch (정렬)", test_scan_mixed_status),
        ("scan_implicit_pending — frontmatter 없으면 implicit pending catch",
         test_scan_implicit_pending),
        ("scan_blocked_skips — status: blocked skip", test_scan_blocked_skips),
        ("scan_root_cause_baseline_vs_msg588 — added·modified 모두 catch (정공법)",
         test_scan_root_cause_baseline_vs_msg588),
    ]

    pass_count = 0
    fail_count = 0
    for name, fn in cases:
        try:
            ok = fn()
        except Exception as e:
            ok = False
            _print_result(name, False, f"EXCEPTION: {type(e).__name__}: {e}")
            fail_count += 1
            continue
        _print_result(name, ok)
        if ok:
            pass_count += 1
        else:
            fail_count += 1

    print()
    print(f"=== 검증 종료 — PASS {pass_count} / FAIL {fail_count} ===")
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
