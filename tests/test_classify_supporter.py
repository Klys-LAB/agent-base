"""tests/test_classify_supporter.py — supporter target classify 단위 테스트 (BILLI msg 594 fix)

목적:
    AGENTS §18.1 통신 표준 [MSG] 헤더 + 본문 '수신자' 헤더 영역 bilingual
    catch (supporter 영어 + 보조자 한국어). 이전 logic '보조자' 단독 의존
    영역 영어 'supporter' 만 사용한 ORDER (BILLI PRE-P3-B-R2) skip 영역
    root cause fix 검증.

실행:
    cd /root/Klys-LAB/agent-base
    python3 tests/test_classify_supporter.py

기대: 모든 case PASS, exit 0.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.poller.poller import order_targets_supporter

# DRY 정합 (BILLI msg 594 fix) — agent-billi.py 측 _is_supporter_target 제거,
# poller.py order_targets_supporter 단독 사용. 본 테스트 = poller.py 함수 단독.


def _print_result(name: str, ok: bool, msg: str = "") -> None:
    icon = "PASS" if ok else "FAIL"
    suffix = f" — {msg}" if msg else ""
    print(f"  [{icon}] {name}{suffix}")


def _make_order(td: Path, name: str, content: str) -> tuple[Path, Path, str]:
    """tmp orders/<name> 작성 + (repo_path, order_path, rel) 반환."""
    od = td / "orders"
    od.mkdir(parents=True, exist_ok=True)
    p = od / name
    p.write_text(content, encoding="utf-8")
    return td, p, f"orders/{name}"


# === order_targets_supporter (poller.py legacy) ===

def test_legacy_korean_baseline():
    """ADR-005-B baseline 패턴 — '수신자: 보조자' (한국어) catch."""
    with tempfile.TemporaryDirectory() as td:
        _, p, _ = _make_order(Path(td), "ORDER-A.md",
                              "# ORDER A\n\n**수신자**: 보조자 (agent-base)\n")
        return order_targets_supporter(p) is True


def test_legacy_english_supporter():
    """msg 594 root cause case — '수신자: supporter' (영어) catch (fix 핵심)."""
    with tempfile.TemporaryDirectory() as td:
        _, p, _ = _make_order(Path(td), "ORDER-B.md",
                              "# ORDER B\n\n**수신자**: supporter (VPS)\n")
        return order_targets_supporter(p) is True


def test_legacy_msg_header_english():
    """[MSG] designer→supporter 영어 헤더 catch."""
    with tempfile.TemporaryDirectory() as td:
        _, p, _ = _make_order(Path(td), "ORDER-C.md",
                              "# ORDER C\n\n[MSG] designer→supporter\n[CTX] x · y\n")
        return order_targets_supporter(p) is True


def test_legacy_msg_header_korean():
    """[MSG] designer→보조자 한국어 헤더 catch."""
    with tempfile.TemporaryDirectory() as td:
        _, p, _ = _make_order(Path(td), "ORDER-D.md",
                              "# ORDER D\n\n[MSG] user→보조자\n")
        return order_targets_supporter(p) is True


def test_legacy_developer_target_skip():
    """수신자: developer 영역 skip."""
    with tempfile.TemporaryDirectory() as td:
        _, p, _ = _make_order(Path(td), "ORDER-E.md",
                              "# ORDER E\n\n**수신자**: developer\n[MSG] user→developer\n")
        return order_targets_supporter(p) is False


def test_legacy_no_recipient():
    """수신자·[MSG] 헤더 둘 다 없으면 skip."""
    with tempfile.TemporaryDirectory() as td:
        _, p, _ = _make_order(Path(td), "ORDER-F.md",
                              "# ORDER F\n\n본문 영역 단독\n")
        return order_targets_supporter(p) is False


def test_legacy_supporter_keyword_alone_no_header():
    """'supporter' keyword 영역 단독 (수신자 헤더·[MSG] 영역 X) → skip.

    배제 영역 — 무관 keyword 단독으로는 dispatch 안 함.
    """
    with tempfile.TemporaryDirectory() as td:
        _, p, _ = _make_order(Path(td), "ORDER-G.md",
                              "# ORDER G\n\n본문 영역 supporter 단어 영역만 있음\n")
        return order_targets_supporter(p) is False


def test_legacy_pr_p3_b_r2_actual():
    """실제 BILLI PRE-P3-B-R2 ORDER 본문 (영어 supporter 만) catch 검증."""
    with tempfile.TemporaryDirectory() as td:
        body = (
            "---\n"
            "status: pending\n"
            "---\n\n"
            "# PRE-P3-B-R2 — tick_value\n\n"
            "**수신자**: supporter (VPS Ubuntu 24.04 + Wine 9.0)\n\n"
            "[MSG] designer→supporter\n"
            "[CTX] phase-3 · PRE-P3-B-R2\n"
            "[TYPE] ORDER  [PRIO] P1  [SIZE] med\n"
            "[GATE] auto\n\n"
            "## OBJECTIVE\n측정한다.\n"
        )
        _, p, _ = _make_order(Path(td), "PRE-P3-B-R2.md", body)
        return order_targets_supporter(p) is True


def test_missing_file():
    """파일 없으면 False (OSError catch)."""
    with tempfile.TemporaryDirectory() as td:
        return order_targets_supporter(Path(td) / "nonexistent.md") is False


# === 메인 runner ===

def main():
    print("=== msg 594 root cause fix 검증 (classify_supporter bilingual) ===")
    print()

    cases = [
        ("legacy_korean_baseline — '수신자: 보조자' catch", test_legacy_korean_baseline),
        ("legacy_english_supporter — '수신자: supporter' catch (root cause fix)",
         test_legacy_english_supporter),
        ("legacy_msg_header_english — '[MSG] →supporter' catch", test_legacy_msg_header_english),
        ("legacy_msg_header_korean — '[MSG] →보조자' catch", test_legacy_msg_header_korean),
        ("legacy_developer_target_skip — developer 대상 skip",
         test_legacy_developer_target_skip),
        ("legacy_no_recipient — 헤더 없으면 skip", test_legacy_no_recipient),
        ("legacy_supporter_keyword_alone — 무관 keyword 단독 skip",
         test_legacy_supporter_keyword_alone_no_header),
        ("legacy_pr_p3_b_r2_actual — 실제 BILLI PRE-P3-B-R2 본문 catch",
         test_legacy_pr_p3_b_r2_actual),
        ("missing_file — 파일 없으면 False (OSError catch)", test_missing_file),
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
