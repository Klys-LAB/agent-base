"""core/dispatch/dispatch.py — claude -p OAuth wrapper (ADR-001 D5 dispatch 모듈)"""
import subprocess
import shutil
from pathlib import Path


def claude_available() -> bool:
    return shutil.which("claude") is not None


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
