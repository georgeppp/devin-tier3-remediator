"""Tiny .env loader used to launch the stack outside Docker.

Reads KEY=VALUE lines from .env in repo root, populates os.environ for the
current process (and any child it execs).
"""
import os
import sys
from pathlib import Path


def load(env_path: Path | None = None) -> dict[str, str]:
    env_path = env_path or Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return {}
    loaded: dict[str, str] = {}
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val
            loaded[key] = val
    return loaded


if __name__ == "__main__":
    keys = load()
    print(f"loaded {len(keys)} env vars: {', '.join(sorted(keys))}", file=sys.stderr)
