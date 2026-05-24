"""End-to-end webhook tests using FastAPI's TestClient. No real Devin calls."""
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

# Ensure repo root + test env vars are set BEFORE importing the app.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEVIN_API_KEY", "test")
os.environ.setdefault("DEVIN_ORG_ID", "test-org")
os.environ["GH_WEBHOOK_SECRET"] = "testsecret"
os.environ["DEVIN_DB_PATH"] = str(ROOT / ".test.db")

from fastapi.testclient import TestClient  # noqa: E402

import src.webhook as webhook_mod  # noqa: E402

client = TestClient(webhook_mod.app)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_rejects_bad_signature():
    r = client.post(
        "/webhook",
        content=b"{}",
        headers={"x-hub-signature-256": "sha256=bad", "x-github-event": "issues"},
    )
    assert r.status_code == 401


def test_skips_non_issue_event():
    body = b'{"action":"opened"}'
    r = client.post(
        "/webhook",
        content=body,
        headers={"x-hub-signature-256": _sign(body), "x-github-event": "push"},
    )
    assert r.status_code == 200
    assert r.json()["skipped"] is True


def test_skips_issue_without_devin_auto_label():
    body = json.dumps(
        {
            "action": "opened",
            "issue": {
                "number": 1,
                "node_id": "x",
                "title": "t",
                "body": "b",
                "html_url": "u",
                "labels": [{"name": "doc-drift"}],
            },
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    r = client.post(
        "/webhook",
        content=body,
        headers={"x-hub-signature-256": _sign(body), "x-github-event": "issues"},
    )
    assert r.status_code == 200
    assert "no devin-auto label" in r.json()["reason"]


def test_queues_when_labeled(monkeypatch):
    fired: list[tuple] = []
    monkeypatch.setattr(
        webhook_mod, "dispatch", lambda issue, repo: fired.append((issue["number"], repo))
    )

    body = json.dumps(
        {
            "action": "labeled",
            "issue": {
                "number": 42,
                "node_id": "I_x",
                "title": "test",
                "body": "b",
                "html_url": "u",
                "labels": [{"name": "devin-auto"}, {"name": "doc-drift"}],
            },
            "repository": {"full_name": "GeorgePPP/superset"},
        }
    ).encode()
    r = client.post(
        "/webhook",
        content=body,
        headers={"x-hub-signature-256": _sign(body), "x-github-event": "issues"},
    )
    assert r.status_code == 200
    assert r.json() == {"queued": True, "issue": 42}

    # Background task fires shortly after response.
    for _ in range(20):
        if fired:
            break
        time.sleep(0.05)
    assert fired == [(42, "GeorgePPP/superset")]
