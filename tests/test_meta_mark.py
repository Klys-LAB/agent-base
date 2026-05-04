"""tests/test_meta_mark.py — ADR-005-B §4 단위 테스트 (parse·write·transition·find_pending)."""
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.meta_mark import (
    MetaMark,
    VALID_STATUSES,
    parse,
    read,
    write,
    transition,
    find_pending,
    is_dispatched_stale,
    now_utc_iso,
)


ORDER_BODY = "# ORDER X — sample\n\n## 1. 목적\n본문 내용.\n"
PENDING_FRONTMATTER = (
    "---\n"
    "status: pending\n"
    "dispatched_at:\n"
    "dispatched_pid:\n"
    "---\n"
)


def _write_order(path: Path, frontmatter: str, body: str = ORDER_BODY) -> None:
    path.write_text(frontmatter + body, encoding="utf-8")


# ─── parse ────────────────────────────────────────────────────────────────


def test_parse_pending_returns_meta_and_body():
    text = PENDING_FRONTMATTER + ORDER_BODY
    meta, body = parse(text)
    assert meta is not None
    assert meta.status == "pending"
    assert meta.dispatched_at == ""
    assert meta.dispatched_pid == ""
    assert body == ORDER_BODY


def test_parse_dispatched_with_values():
    text = (
        "---\n"
        "status: dispatched\n"
        "dispatched_at: 2026-05-04T09:30:00Z\n"
        "dispatched_pid: 12345\n"
        "---\n"
    ) + ORDER_BODY
    meta, body = parse(text)
    assert meta.status == "dispatched"
    assert meta.dispatched_at == "2026-05-04T09:30:00Z"
    assert meta.dispatched_pid == "12345"
    assert body == ORDER_BODY


def test_parse_no_frontmatter_returns_none():
    text = ORDER_BODY
    meta, body = parse(text)
    assert meta is None
    assert body == text


def test_parse_unterminated_frontmatter_returns_none():
    text = "---\nstatus: pending\n" + ORDER_BODY
    meta, body = parse(text)
    assert meta is None
    assert body == text


# ─── read / write ─────────────────────────────────────────────────────────


def test_read_missing_file_returns_none(tmp_path):
    assert read(tmp_path / "nonexistent.md") is None


def test_write_preserves_body_byte_for_byte(tmp_path):
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)
    new_meta = MetaMark("dispatched", "2026-05-04T10:00:00Z", "999")
    write(p, new_meta)
    text = p.read_text(encoding="utf-8")
    assert text.endswith(ORDER_BODY)
    assert "status: dispatched" in text
    assert "dispatched_at: 2026-05-04T10:00:00Z" in text
    assert "dispatched_pid: 999" in text


def test_write_invalid_status_raises(tmp_path):
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)
    with pytest.raises(ValueError):
        write(p, MetaMark("running"))


# ─── transition ───────────────────────────────────────────────────────────


def test_transition_pending_to_dispatched_stamps_pid_and_time(tmp_path):
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)
    ok, meta = transition(p, "pending", "dispatched", pid=12345)
    assert ok is True
    assert meta.status == "dispatched"
    assert meta.dispatched_pid == "12345"
    # ISO 8601, ends with Z, contains T
    assert meta.dispatched_at.endswith("Z")
    assert "T" in meta.dispatched_at


def test_transition_pending_to_dispatched_default_pid_is_os_getpid(tmp_path):
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)
    ok, meta = transition(p, "pending", "dispatched")
    assert ok is True
    assert meta.dispatched_pid == str(os.getpid())


def test_transition_status_mismatch_returns_false_no_write(tmp_path):
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)
    ok, meta = transition(p, "dispatched", "done")
    assert ok is False
    # File untouched — still pending
    cur = read(p)
    assert cur.status == "pending"


def test_transition_dispatched_to_done_preserves_audit(tmp_path):
    p = tmp_path / "o.md"
    fm = (
        "---\n"
        "status: dispatched\n"
        "dispatched_at: 2026-05-04T09:30:00Z\n"
        "dispatched_pid: 7777\n"
        "---\n"
    )
    _write_order(p, fm, ORDER_BODY)
    ok, meta = transition(p, "dispatched", "done")
    assert ok is True
    assert meta.status == "done"
    assert meta.dispatched_at == "2026-05-04T09:30:00Z"
    assert meta.dispatched_pid == "7777"


def test_transition_dispatched_to_pending_clears_audit(tmp_path):
    p = tmp_path / "o.md"
    fm = (
        "---\n"
        "status: dispatched\n"
        "dispatched_at: 2026-05-04T09:30:00Z\n"
        "dispatched_pid: 7777\n"
        "---\n"
    )
    _write_order(p, fm, ORDER_BODY)
    ok, meta = transition(p, "dispatched", "pending")
    assert ok is True
    assert meta.status == "pending"
    assert meta.dispatched_at == ""
    assert meta.dispatched_pid == ""


def test_transition_invalid_target_returns_false(tmp_path):
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)
    ok, _ = transition(p, "pending", "running")
    assert ok is False


def test_transition_legacy_no_frontmatter_returns_false(tmp_path):
    p = tmp_path / "o.md"
    p.write_text(ORDER_BODY, encoding="utf-8")  # no frontmatter
    ok, meta = transition(p, "pending", "dispatched")
    assert ok is False
    assert meta is None


# ─── find_pending ─────────────────────────────────────────────────────────


def test_find_pending_returns_only_pending_orders(tmp_path):
    orders = tmp_path / "orders"
    orders.mkdir()
    _write_order(orders / "A.md", PENDING_FRONTMATTER)
    _write_order(orders / "B.md", "---\nstatus: dispatched\ndispatched_at: 2026-05-04T09:00:00Z\ndispatched_pid: 1\n---\n")
    _write_order(orders / "C.md", "---\nstatus: done\ndispatched_at: 2026-05-04T09:00:00Z\ndispatched_pid: 1\n---\n")
    _write_order(orders / "D.md", PENDING_FRONTMATTER)
    # legacy without frontmatter — must not appear
    (orders / "Legacy.md").write_text(ORDER_BODY, encoding="utf-8")

    result = find_pending(tmp_path, "orders/")
    assert result == ["orders/A.md", "orders/D.md"]


def test_find_pending_missing_dir_returns_empty(tmp_path):
    assert find_pending(tmp_path, "orders/") == []


# ─── is_dispatched_stale ──────────────────────────────────────────────────


def test_is_dispatched_stale_false_for_recent(tmp_path):
    p = tmp_path / "o.md"
    fm = (
        "---\n"
        "status: dispatched\n"
        f"dispatched_at: {now_utc_iso()}\n"
        "dispatched_pid: 1\n"
        "---\n"
    )
    _write_order(p, fm, ORDER_BODY)
    assert is_dispatched_stale(p, timeout_sec=3600) is False


def test_is_dispatched_stale_true_for_old(tmp_path):
    p = tmp_path / "o.md"
    fm = (
        "---\n"
        "status: dispatched\n"
        "dispatched_at: 2020-01-01T00:00:00Z\n"
        "dispatched_pid: 1\n"
        "---\n"
    )
    _write_order(p, fm, ORDER_BODY)
    assert is_dispatched_stale(p, timeout_sec=3600) is True


def test_is_dispatched_stale_false_when_status_not_dispatched(tmp_path):
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)
    assert is_dispatched_stale(p) is False


def test_is_dispatched_stale_false_for_malformed_timestamp(tmp_path):
    p = tmp_path / "o.md"
    fm = (
        "---\n"
        "status: dispatched\n"
        "dispatched_at: not-a-valid-iso-string\n"
        "dispatched_pid: 1\n"
        "---\n"
    )
    _write_order(p, fm, ORDER_BODY)
    assert is_dispatched_stale(p) is False


# ─── round-trip preservation ──────────────────────────────────────────────


def test_round_trip_through_full_lifecycle(tmp_path):
    """pending -> dispatched -> done sequence preserves body and updates header."""
    p = tmp_path / "o.md"
    _write_order(p, PENDING_FRONTMATTER, ORDER_BODY)

    ok, _ = transition(p, "pending", "dispatched", pid=42)
    assert ok
    ok, _ = transition(p, "dispatched", "done")
    assert ok

    final = read(p)
    assert final.status == "done"
    assert final.dispatched_pid == "42"
    assert p.read_text(encoding="utf-8").endswith(ORDER_BODY)
