"""core/lib/config.py — config.yml + secrets.env 로더 (ADR-001 D4)"""
import os
import yaml
from pathlib import Path

AGENT_BASE = Path(__file__).resolve().parents[3]


def load_config(project: str) -> dict:
    path = AGENT_BASE / "projects" / project / "config.yml"
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def load_secrets(project: str) -> dict:
    path = AGENT_BASE / "projects" / project / "secrets.env"
    secrets = {}
    if not path.exists():
        return secrets
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            secrets[k.strip()] = v.strip()
    return secrets


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
