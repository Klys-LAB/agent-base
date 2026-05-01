"""core/log/logger.py — 구조화 로그 (ADR-001 D5 log 모듈)"""
import json
import sys
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(level: str, project: str, module: str, msg: str, **kv) -> None:
    record = {"ts": _now(), "level": level, "project": project, "module": module, "msg": msg}
    record.update(kv)
    print(json.dumps(record, ensure_ascii=False), file=sys.stdout, flush=True)


def info(project: str, module: str, msg: str, **kv) -> None:
    _emit("INFO", project, module, msg, **kv)


def warn(project: str, module: str, msg: str, **kv) -> None:
    _emit("WARN", project, module, msg, **kv)


def error(project: str, module: str, msg: str, **kv) -> None:
    _emit("ERROR", project, module, msg, **kv)
