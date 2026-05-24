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


def _reload_with_db(monkeypatch, tmp_path, name: str):
    db_path = tmp_path / name
    monkeypatch.setenv("DEVIN_DB_PATH", str(db_path))
    import importlib

    import src.db as db_mod
    import src.orchestrator as orch
    importlib.reload(db_mod)
    importlib.reload(orch)
    db_mod.init()
    return db_mod, orch


def test_dispatch_dedupes_on_node_id(monkeypatch, tmp_path):
    """Second dispatch for the same issue.node_id must NOT call create_session."""
    _, orch = _reload_with_db(monkeypatch, tmp_path, "dedup.db")

    calls: list[str] = []

    def fake_create(prompt, idempotency_key, tags, title=None):
        calls.append(idempotency_key)
        return {"session_id": "sess-1", "url": "https://x"}

    monkeypatch.setattr(orch, "create_session", fake_create)

    issue = {
        "number": 7,
        "node_id": "I_dup",
        "title": "t",
        "body": "b",
        "html_url": "u",
        "labels": [{"name": "doc-drift"}],
    }
    first = orch.dispatch(issue, "o/r")
    second = orch.dispatch(issue, "o/r")
    assert first is not None and not first.get("deduped")
    assert second is not None and second.get("deduped") is True
    assert calls == ["I_dup"], "create_session must have been called exactly once"


def test_dispatch_is_race_safe_under_concurrency(monkeypatch, tmp_path):
    """3 concurrent dispatches for the same issue must produce exactly 1 session.

    Reproduces the GitHub `opened + labeled + labeled` triple-fire scenario.
    """
    import threading
    import time as _time

    _, orch = _reload_with_db(monkeypatch, tmp_path, "race.db")

    call_count = {"n": 0}
    lock = threading.Lock()

    def slow_create(prompt, idempotency_key, tags, title=None):
        # Simulate the network call; the longer this sleep, the more chance
        # of a races without the INSERT OR IGNORE reservation.
        _time.sleep(0.05)
        with lock:
            call_count["n"] += 1
            n = call_count["n"]
        return {"session_id": f"sess-{n}", "url": "https://x"}

    monkeypatch.setattr(orch, "create_session", slow_create)

    issue = {
        "number": 8,
        "node_id": "I_race",
        "title": "t",
        "body": "b",
        "html_url": "u",
        "labels": [{"name": "doc-drift"}],
    }
    threads = [threading.Thread(target=orch.dispatch, args=(issue, "o/r")) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert call_count["n"] == 1, f"expected exactly 1 Devin call, got {call_count['n']}"


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
