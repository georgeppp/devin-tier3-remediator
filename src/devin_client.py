"""Thin wrapper over the Devin v3 organization API.

Endpoints used:
- POST /v3/organizations/{org}/sessions
- GET  /v3/organizations/{org}/sessions/{session_id}
- POST /v3/organizations/{org}/sessions/{session_id}/messages
- POST /v3/organizations/{org}/knowledge/notes
"""
import os

import requests

API = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai")
ORG = os.environ.get("DEVIN_ORG_ID", "")
KEY = os.environ.get("DEVIN_API_KEY", "")
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def _org_url(suffix: str) -> str:
    if not ORG:
        raise RuntimeError("DEVIN_ORG_ID is not set")
    return f"{API}/v3/organizations/{ORG}{suffix}"


def create_session(prompt: str, idempotency_key: str, tags: list[str], title: str | None = None):
    """Create a Devin session.

    `idempotency_key` is accepted only for API symmetry with the orchestrator
    layer; the v3 API does NOT support server-side request dedup. We tag the
    session with it so the issue can still be correlated from the Devin UI.
    """
    payload: dict = {
        "prompt": prompt,
        "tags": list(tags) + [f"idem:{idempotency_key}"],
    }
    if title:
        payload["title"] = title
    r = requests.post(_org_url("/sessions"), headers=H, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def get_session(session_id: str):
    r = requests.get(_org_url(f"/sessions/{session_id}"), headers=H, timeout=30)
    r.raise_for_status()
    return r.json()


def send_message(session_id: str, message: str):
    r = requests.post(
        _org_url(f"/sessions/{session_id}/messages"),
        headers=H,
        json={"message": message},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def create_knowledge(name: str, body: str, trigger_description: str):
    """Create a knowledge note under the org. v3 endpoint: /knowledge/notes."""
    r = requests.post(
        _org_url("/knowledge/notes"),
        headers=H,
        json={
            "name": name,
            "body": body,
            "trigger": trigger_description,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
