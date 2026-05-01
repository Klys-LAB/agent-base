"""core/report/report.py — §18 REPORT 생성 헬퍼 (ADR-001 D5 report 모듈)"""
from datetime import datetime, timezone


def build(
    sender: str,
    receiver: str,
    ctx_phase: str,
    ctx_topic: str,
    result: str,
    artifacts: list[str],
    checks: list[tuple[str, str]],
    blocks: list[str],
    next_step: str,
    ref: str = "",
    prio: str = "P1",
    size: str = "short",
) -> str:
    header = (
        f"[MSG] {sender}→{receiver}\n"
        f"[CTX] {ctx_phase} · {ctx_topic}\n"
        f"[TYPE] REPORT  [PRIO] {prio}  [SIZE] {size}"
    )
    ref_line = f"\nREF: {ref}" if ref else ""
    artifact_lines = "\n".join(f"- {a}" for a in artifacts) or "- 없음"
    check_lines = "\n".join(f"- {cmd}: {out}" for cmd, out in checks) or "- 없음"
    block_lines = "\n".join(f"- {b}" for b in blocks) or "- 없음"

    return (
        f"{header}{ref_line}\n\n"
        f"## RESULT\n{result}\n\n"
        f"## ARTIFACT\n{artifact_lines}\n\n"
        f"## CHECK\n{check_lines}\n\n"
        f"## BLOCK\n{block_lines}\n\n"
        f"## NEXT\n{next_step}"
    )
