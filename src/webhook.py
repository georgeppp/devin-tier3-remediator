"""FastAPI receiver for GitHub `issues` webhooks.

Verifies HMAC, filters for `devin-auto`-labeled issues, then hands off to the
orchestrator in a background task so we can return 200 within GitHub's 10s budget.
"""
import hashlib
import hmac
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from src.db import init
from src.orchestrator import dispatch

SECRET = os.environ.get("GH_WEBHOOK_SECRET", "").encode()
TRIGGER_LABEL = "devin-auto"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init()
    yield


app = FastAPI(title="Tier-3 Backlog Auto-Remediator", lifespan=lifespan)


def _verify(body: bytes, sig: str | None) -> None:
    if not SECRET:
        # No secret configured: refuse to verify so we never silently accept unsigned payloads.
        raise HTTPException(500, "GH_WEBHOOK_SECRET not configured on the server")
    expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig or ""):
        raise HTTPException(401, "bad signature")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/webhook")
async def webhook(req: Request, bg: BackgroundTasks):
    body = await req.body()
    _verify(body, req.headers.get("x-hub-signature-256"))

    if req.headers.get("x-github-event") != "issues":
        return {"skipped": True, "reason": "not an issues event"}

    payload = await req.json()
    action = payload.get("action")
    if action not in ("opened", "labeled", "reopened"):
        return {"skipped": True, "reason": f"action={action}"}

    issue = payload["issue"]
    repo = payload["repository"]["full_name"]

    label_names = [l["name"] for l in issue.get("labels", [])]
    if TRIGGER_LABEL not in label_names:
        return {"skipped": True, "reason": f"no {TRIGGER_LABEL} label"}

    bg.add_task(dispatch, issue, repo)
    return {"queued": True, "issue": issue["number"]}
