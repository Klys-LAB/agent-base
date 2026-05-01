"""core/health/health.py — 의존성 점검 (ADR-001 D5 health 모듈, D7 잔재 0 원칙)"""
import shutil
import subprocess

REQUIRED = ["bash", "python3", "git", "gh", "jq"]
FORBIDDEN = ["pwsh", "powershell", "rclone"]


def check() -> dict:
    result = {"required": {}, "forbidden_present": []}
    for dep in REQUIRED:
        result["required"][dep] = shutil.which(dep) is not None
    for dep in FORBIDDEN:
        if shutil.which(dep):
            result["forbidden_present"].append(dep)
    result["all_required_ok"] = all(result["required"].values())
    result["residue_zero"] = len(result["forbidden_present"]) == 0
    return result


def report_str() -> str:
    h = check()
    lines = ["=== agent-base health check ==="]
    for dep, ok in h["required"].items():
        lines.append(f"  {'OK' if ok else 'MISSING'}: {dep}")
    if h["forbidden_present"]:
        lines.append(f"  WARN 잔재: {', '.join(h['forbidden_present'])}")
    lines.append(f"required OK: {h['all_required_ok']}")
    lines.append(f"잔재 0: {h['residue_zero']}")
    return "\n".join(lines)
