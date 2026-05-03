"""core/poller/order_meta.py — ORDER YAML front matter 파싱·갱신 (BILLI ORDER msg 466 C-2, AGENTS §19.6)

ORDER 본문 상단에 YAML-style 메타마커:

    ---
    status: pending
    dispatched_at:
    dispatched_pid:
    ---

    # ORDER-TAG — Title
    ...

status 전이:
    pending → dispatched → done | failed
    pending → blocked (사용자 결정 영역, [GATE] user 또는 외부 차단)

cross-host idempotency:
    - status: dispatched 인 ORDER 는 다른 host (Mac·VPS) 에서 skip
    - state/<order>.json 와 함께 두 트랙 idempotency
"""
import re
from datetime import datetime, timezone
from pathlib import Path

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_ALLOWED_STATUS = {"pending", "dispatched", "done", "failed", "blocked"}


def read_meta(order_path: Path) -> dict:
    """ORDER 파일의 YAML front matter 파싱. 없으면 implicit pending."""
    if not order_path.exists():
        return {"status": "missing"}
    text = order_path.read_text(encoding="utf-8")
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {"status": "pending"}
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta or {"status": "pending"}


def write_meta(order_path: Path, **kwargs) -> bool:
    """ORDER 파일 front matter 갱신·신설.

    기존 front matter 있으면 merge. 없으면 파일 최상단에 prepend.
    status 검증 — _ALLOWED_STATUS 외는 ValueError.
    """
    if not order_path.exists():
        return False

    if "status" in kwargs and kwargs["status"] not in _ALLOWED_STATUS:
        raise ValueError(f"invalid status: {kwargs['status']}, must be one of {_ALLOWED_STATUS}")

    text = order_path.read_text(encoding="utf-8")
    m = _FRONT_MATTER_RE.match(text)

    if m:
        existing = {}
        for line in m.group(1).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and ":" in line:
                k, _, v = line.partition(":")
                existing[k.strip()] = v.strip()
        # merge — kwargs 가 우선
        for k, v in kwargs.items():
            existing[k] = "" if v is None else str(v)
        new_fm = "---\n" + "\n".join(f"{k}: {v}" for k, v in existing.items()) + "\n---\n"
        new_text = new_fm + text[m.end():]
    else:
        new_meta = {k: ("" if v is None else str(v)) for k, v in kwargs.items()}
        new_fm = "---\n" + "\n".join(f"{k}: {v}" for k, v in new_meta.items()) + "\n---\n\n"
        new_text = new_fm + text

    order_path.write_text(new_text, encoding="utf-8")
    return True


def mark_dispatched(order_path: Path, pid: int | None = None) -> bool:
    """ORDER status → dispatched + dispatched_at·dispatched_pid 기록."""
    import os
    return write_meta(
        order_path,
        status="dispatched",
        dispatched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        dispatched_pid=str(pid if pid is not None else os.getpid()),
    )


def mark_done(order_path: Path) -> bool:
    return write_meta(order_path, status="done")


def mark_failed(order_path: Path) -> bool:
    return write_meta(order_path, status="failed")


def is_dispatchable(order_path: Path) -> bool:
    """pending 상태만 dispatch 가능. dispatched·done·failed·blocked 는 skip."""
    meta = read_meta(order_path)
    return meta.get("status", "pending") == "pending"


def ensure_pending(order_path: Path) -> bool:
    """front matter 없으면 status: pending 으로 초기화. 이미 있으면 변경 없음."""
    if not order_path.exists():
        return False
    text = order_path.read_text(encoding="utf-8")
    if _FRONT_MATTER_RE.match(text):
        return False  # 이미 메타 있음
    write_meta(order_path, status="pending", dispatched_at="", dispatched_pid="")
    return True
