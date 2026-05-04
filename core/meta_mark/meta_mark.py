"""core/meta_mark/meta_mark.py — ORDER frontmatter schema (ADR-005-B §3).

Schema (4 필드 한정, ORDER §3.1 정합):

    ---
    status: pending | dispatched | done | failed
    dispatched_at: <ISO 8601 UTC, 예: 2026-05-04T09:30:00Z>
    dispatched_pid: <agent PID>
    ---

Transition 표 (ORDER §3.2, atomic):

    pending    -> dispatched   (poller cycle, dispatched_at·dispatched_pid 기록)
    dispatched -> done         (작업 완료)
    dispatched -> failed       (작업 실패·timeout, 호출 측 ⚠️ Telegram)
    dispatched -> pending      (stale 1h, dispatched_at·dispatched_pid clear)

각 transition 은 in-process atomic — read-validate-write 한 호출. commit+push 는
호출 측 (poller / agent-billi) 책임 (atomic 묶음 구성).
"""
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VALID_STATUSES = ("pending", "dispatched", "done", "failed")
DELIMITER = "---"

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass
class MetaMark:
    status: str
    dispatched_at: str = ""
    dispatched_pid: str = ""

    def to_block(self) -> str:
        """Render as YAML frontmatter block (4 lines + 2 delimiters)."""
        return (
            f"{DELIMITER}\n"
            f"status: {self.status}\n"
            f"dispatched_at: {self.dispatched_at}\n"
            f"dispatched_pid: {self.dispatched_pid}\n"
            f"{DELIMITER}\n"
        )


def now_utc_iso() -> str:
    """ISO 8601 UTC, second precision, Z suffix."""
    return datetime.now(timezone.utc).strftime(_ISO_FMT)


def parse(text: str) -> tuple[Optional[MetaMark], str]:
    """Parse ORDER text. Returns (meta, body).

    meta = None when no frontmatter present (legacy ORDER without schema).
    body excludes the frontmatter block.
    """
    lines = text.splitlines(keepends=True)
    if not lines:
        return None, text
    if lines[0].rstrip("\r\n") != DELIMITER:
        return None, text
    end_idx: Optional[int] = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == DELIMITER:
            end_idx = i
            break
    if end_idx is None:
        return None, text
    fields: dict[str, str] = {}
    for ln in lines[1:end_idx]:
        s = ln.strip()
        if not s or ":" not in s:
            continue
        k, _, v = s.partition(":")
        fields[k.strip()] = v.strip()
    body = "".join(lines[end_idx + 1:])
    meta = MetaMark(
        status=fields.get("status", ""),
        dispatched_at=fields.get("dispatched_at", ""),
        dispatched_pid=fields.get("dispatched_pid", ""),
    )
    return meta, body


def read(order_path: Path) -> Optional[MetaMark]:
    """Read frontmatter from ORDER file. None if file missing or no frontmatter."""
    if not order_path.exists():
        return None
    try:
        text = order_path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, _ = parse(text)
    return meta


def write(order_path: Path, meta: MetaMark) -> None:
    """Atomic write — replace frontmatter block, body unchanged.

    Uses tmpfile + os.replace for atomic semantics on POSIX. Body is preserved
    byte-for-byte; frontmatter block is regenerated from `meta`.
    """
    if meta.status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {meta.status!r}")
    text = order_path.read_text(encoding="utf-8")
    _, body = parse(text)
    new_text = meta.to_block() + body
    tmp_dir = order_path.parent
    fd, tmp_name = tempfile.mkstemp(dir=str(tmp_dir), prefix=".meta_mark.", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp_name, str(order_path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def transition(
    order_path: Path,
    from_status: str,
    to_status: str,
    pid: Optional[int] = None,
) -> tuple[bool, Optional[MetaMark]]:
    """CAS-style transition. Atomic in-process.

    - from_status/to_status must both be in VALID_STATUSES.
    - Reads current meta. If status != from_status, returns (False, current_meta).
    - On `pending -> dispatched`: stamps dispatched_at = now, dispatched_pid = pid or os.getpid().
    - On `dispatched -> pending` (stale release): clears dispatched_at + dispatched_pid.
    - On `dispatched -> done` / `dispatched -> failed`: preserves dispatched_at + dispatched_pid
      so audit trail survives.

    Returns (ok, new_meta_or_current).
    """
    if from_status not in VALID_STATUSES or to_status not in VALID_STATUSES:
        return False, None
    meta = read(order_path)
    if meta is None or meta.status != from_status:
        return False, meta

    new_at = meta.dispatched_at
    new_pid = meta.dispatched_pid

    if from_status == "pending" and to_status == "dispatched":
        new_at = now_utc_iso()
        new_pid = str(pid if pid is not None else os.getpid())
    elif from_status == "dispatched" and to_status == "pending":
        new_at = ""
        new_pid = ""

    new_meta = MetaMark(status=to_status, dispatched_at=new_at, dispatched_pid=new_pid)
    write(order_path, new_meta)
    return True, new_meta


def find_pending(repo_path: Path, orders_dir: str = "orders/") -> list[str]:
    """Scan orders_dir for ORDERs with status: pending. Returns repo-relative paths sorted."""
    base = repo_path / orders_dir
    if not base.is_dir():
        return []
    out: list[str] = []
    for p in sorted(base.glob("*.md")):
        meta = read(p)
        if meta is not None and meta.status == "pending":
            out.append(str(p.relative_to(repo_path)))
    return out


def is_dispatched_stale(order_path: Path, timeout_sec: int = 3600) -> bool:
    """True iff ORDER is `dispatched` and dispatched_at is older than timeout_sec.

    Used to release stale locks (ORDER §3.2 row 4): caller transitions
    dispatched -> pending so the next cycle re-dispatches.
    """
    meta = read(order_path)
    if meta is None or meta.status != "dispatched":
        return False
    ts = meta.dispatched_at
    if not ts:
        return False
    try:
        dt = datetime.strptime(ts, _ISO_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return age > timeout_sec
