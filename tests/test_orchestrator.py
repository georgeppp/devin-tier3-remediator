"""Unit tests for the classifier and prompt composer."""
import os
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `import src...` resolves under pytest.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub env vars the modules import at top level.
os.environ.setdefault("DEVIN_API_KEY", "test")
os.environ.setdefault("DEVIN_ORG_ID", "test-org")
os.environ.setdefault("GH_WEBHOOK_SECRET", "test")

from src.orchestrator import PLAYBOOK_MAP, classify, compose_prompt  # noqa: E402


def test_classify_known_label():
    assert classify(["devin-auto", "security-fix"]) == "security-fix"
    assert classify(["dep-upgrade"]) == "dep-upgrade"
    assert classify(["doc-drift", "devin-auto"]) == "doc-drift"


def test_classify_unknown_label_returns_none():
    assert classify(["devin-auto"]) is None
    assert classify([]) is None
    assert classify(["something-else"]) is None


def test_all_playbooks_exist_on_disk():
    for fname in PLAYBOOK_MAP.values():
        assert (ROOT / "playbooks" / fname).exists(), f"missing {fname}"


def test_compose_prompt_contains_playbook_and_issue():
    issue = {
        "number": 42,
        "node_id": "I_abc",
        "title": "[Docs] fix dev setup",
        "body": "outdated commands",
        "html_url": "https://github.com/org/repo/issues/42",
        "labels": [{"name": "doc-drift"}, {"name": "devin-auto"}],
    }
    prompt = compose_prompt(issue, "doc-drift", "org/repo")
    assert "Doc Drift Fix" in prompt  # from the playbook
    assert "#42" in prompt
    assert "outdated commands" in prompt
    assert "org/repo" in prompt
    assert "Follow the playbook above" in prompt
