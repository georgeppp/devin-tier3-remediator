"""Upload all entries from knowledge/superset_knowledge.yaml to Devin.

Run once after setting DEVIN_API_KEY and DEVIN_ORG_ID in the environment.
"""
import sys
from pathlib import Path

import yaml

# Allow `python scripts/setup_knowledge.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.devin_client import create_knowledge  # noqa: E402

YAML_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "superset_knowledge.yaml"


def main() -> int:
    entries = yaml.safe_load(YAML_PATH.read_text())
    failures = 0
    for e in entries:
        try:
            res = create_knowledge(e["name"], e["body"], e["trigger"])
            print(f"OK  {e['name']:40s} -> {res}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR {e['name']:40s} -> {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
