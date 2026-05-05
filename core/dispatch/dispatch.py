"""core/dispatch/dispatch.py — ORDER 발견 + claude -p OAuth wrapper (ADR-001 D5 + ADR-005-B §2 Step 1).

ORDER source 단일 진실 = 메타마커 (ORDER §3.3) — 본 모듈의 discover_pending_orders 가 primary.
본문 텍스트 검색·gh PR state 검색은 폐기 (메타마커 단독). gh state 는 보조 검증으로만.
"""
import shutil
import subprocess
from pathlib import Path

from core.meta_mark import find_pending


def claude_available() -> bool:
    return shutil.which("claude") is not None


def discover_pending_orders(repo_path: Path, orders_dir: str = "orders/") -> list[str]:
    """ORDER discovery primary path — 메타마커 status: pending 검색 (ADR-005-B §2 Step 1).

    본문 텍스트 검색·gh PR state 검색 폐기 (ORDER §3.3). gh state 는 보조 검증으로만
    사용 (예: PR # 미발행 ORDER 도 메타마커 단독으로 dispatch).

    Returns repo-relative paths sorted (예: ["orders/S-007-classify-order-fix.md", ...]).
    """
    return find_pending(repo_path, orders_dir)


def run_order(
    work_dir: Path,
    prompt: str,
    max_turns: int = 100,
    max_budget_usd: float = 5.00,
    allowed_tools: list[str] | None = None,
) -> tuple[int, str]:
    if allowed_tools is None:
        allowed_tools = ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]

    tools_str = ",".join(allowed_tools)
    cmd = [
        "claude", "-p", prompt,
        "--max-turns", str(max_turns),
        "--max-budget-usd", str(max_budget_usd),
        "--allowedTools", tools_str,
        "--output-format", "text",
    ]
    r = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True, timeout=1800)
    return r.returncode, (r.stdout + r.stderr).strip()
