"""core/meta_mark — ORDER frontmatter 메타마커 스키마 (ADR-005-B §3, AGENTS §19.6 v1.7).

Public API:
    MetaMark, parse, read, write, transition, find_pending,
    is_dispatched_stale, now_utc_iso, VALID_STATUSES.
"""
from .meta_mark import (
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

__all__ = [
    "MetaMark",
    "VALID_STATUSES",
    "parse",
    "read",
    "write",
    "transition",
    "find_pending",
    "is_dispatched_stale",
    "now_utc_iso",
]
