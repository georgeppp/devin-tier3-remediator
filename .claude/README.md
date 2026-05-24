# Tier-3 Backlog Auto-Remediator — Build Spec

> Handoff document for Claude Code. Everything needed to build the system end-to-end. No demo content, no Loom script — implementation only.

---

## 1. Task Objective

Build a working event-driven automation that uses the [Devin API](https://docs.devin.ai/api-reference/overview) as a core primitive to remediate engineering backlog issues in a forked Apache Superset repository.

**The system must:**
- Be triggered by a GitHub event (issue creation with a specific label)
- Programmatically create and manage Devin sessions
- Produce observable outputs (PRs, dashboard, logs)
- Demonstrate Devin's harness primitives — not just call the API once

**The submission consists of:**
- A public automation repo (this codebase, Dockerized)
- A public fork of `apache/superset` with 6 created issues
- A Loom video (out of scope for this doc)

---

## 2. Mental Model — How Devin Works

Devin has four orchestration layers. **You compose them; you don't replace them with prompts.**

| Layer | What it is | Set up when | Persists |
|---|---|---|---|
| **Knowledge** | Org/repo-level context, auto-recalled by trigger | Once, at setup | Forever, across all sessions |
| **Playbooks** | Task-type templates (`.devin.md` files) | Once per task type | Reused per task type |
| **Snapshots** | Pre-baked VM state (deps installed) | Once, at repo onboarding | Per repo |
| **Sessions** | Single units of work, created via API | Per issue | One task lifecycle |

**Rule of thumb:**
- Anything you'd say to *every* Devin → Knowledge
- Anything you'd say to *every Devin doing task X* → Playbook
- Anything specific to *this* issue → Session prompt

Session prompts should be **short** — Knowledge + Playbook do the heavy lifting.

**The automation loop:**
```
GitHub issue created with `devin-auto` label
        ↓
Webhook fires → FastAPI receiver verifies HMAC
        ↓
Orchestrator classifies issue by label → selects Playbook
        ↓
Compose short session prompt (playbook + issue body)
        ↓
POST /v3/.../sessions with idempotency_key = issue.node_id
        ↓
Poller watches session every 30s, writes to SQLite
        ↓
If CI fails on PR → POST follow-up message to SAME session
        ↓
Dashboard reads SQLite + Devin usage metrics API
```

---

## 3. High-Level Architecture

```
                ┌──────────────────────┐
[GitHub Issue   │   Webhook receiver   │   FastAPI, verifies HMAC signature
 labeled        │   (FastAPI)          │   Returns 200 immediately,
 'devin-auto'] →│                      │   enqueues to background task
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │     Orchestrator     │   Classify issue by label
                │                      │   Load matching playbook
                │  - Label classifier  │   Compose prompt
                │  - Playbook loader   │   Generate idempotency key
                │  - Prompt composer   │
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │   Devin Sessions API │   POST /v3/.../sessions
                │   (parallel sessions)│   with idempotency_key
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │    Status poller     │   Polls every 30s
                │   + SQLite           │   Persists: session_id, status,
                │                      │   pr_url, acu_consumed
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │    Feedback loop     │   On CI failure → POST follow-up
                │                      │   message to existing session
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │   Dashboard (Streamlit)│  Status, throughput, success rate,
                │                       │   ACU cost, hours saved
                └──────────────────────┘
```

---

## 4. Repository Structure

```
devin-tier3-remediator/
├── README.md
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── scripts/
│   └── setup_knowledge.py
├── src/
│   ├── __init__.py
│   ├── webhook.py
│   ├── orchestrator.py
│   ├── devin_client.py
│   ├── poller.py
│   ├── db.py
│   └── dashboard.py
├── playbooks/
│   ├── security_fix.devin.md
│   ├── dep_upgrade.devin.md
│   ├── js_to_ts.devin.md
│   ├── lint_debt.devin.md
│   └── doc_drift.devin.md
├── knowledge/
│   └── superset_knowledge.yaml
└── tests/
    └── test_orchestrator.py
```

---

## 5. Step-by-Step Build Guide

### Step 5.1 — Prerequisites

External setup that must be done before running code:

1. **Devin account** — sign up at app.devin.ai. Generate API key (`cog_...`). Note `DEVIN_ORG_ID`.
2. **GitHub fork** — `gh repo fork apache/superset --clone=false`
3. **Empty repo** for this automation — `gh repo create devin-tier3-remediator --public`
4. **smee.io channel** — for local webhook forwarding. Get URL.
5. **Repo onboarded in Devin UI** — Settings → Repositories → Add fork URL. Accept setup suggestions. Save snapshot. Required commands in the setup:
   - Install: `pip install -e ".[dev]" && cd superset-frontend && npm ci`
   - Test (Python): `pytest tests/unit_tests/ -x`
   - Test (Frontend): `cd superset-frontend && npm test -- --watchAll=false`
   - Lint: `pre-commit run --all-files`

### Step 5.2 — Repo skeleton

Create the directory structure from Section 4. Use empty `__init__.py` for `src/`.

`pyproject.toml`:
```toml
[project]
name = "devin-tier3-remediator"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi",
    "uvicorn",
    "requests",
    "streamlit",
    "pandas",
    "pyyaml",
]
```

`.env.example`:
```
DEVIN_API_KEY=cog_xxx
DEVIN_ORG_ID=xxx
GH_WEBHOOK_SECRET=xxx
```

### Step 5.3 — Playbooks (write these BEFORE Python code)

Five files in `playbooks/`. They share the same shape: Workflow → Stop Conditions → PR Template → Out of Scope. Full contents in Section 6.

### Step 5.4 — Knowledge YAML

`knowledge/superset_knowledge.yaml` — full contents in Section 7.

### Step 5.5 — Knowledge upload script

`scripts/setup_knowledge.py`:
```python
import os, requests, yaml

API = "https://api.devin.ai"
ORG = os.environ["DEVIN_ORG_ID"]
KEY = os.environ["DEVIN_API_KEY"]
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

entries = yaml.safe_load(open("knowledge/superset_knowledge.yaml"))
for e in entries:
    r = requests.post(
        f"{API}/v3/organizations/{ORG}/knowledge",
        headers=H,
        json={
            "name": e["name"],
            "body": e["body"],
            "trigger_description": e["trigger"],
        },
    )
    print(e["name"], r.status_code, r.text[:200])
```

Run once: `python scripts/setup_knowledge.py`. Verify entries appear in Devin UI under Knowledge.

### Step 5.6 — Devin client

`src/devin_client.py`:
```python
import os
import requests

API = "https://api.devin.ai"
ORG = os.environ["DEVIN_ORG_ID"]
KEY = os.environ["DEVIN_API_KEY"]
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def create_session(prompt: str, idempotency_key: str, tags: list[str]):
    payload = {
        "prompt": prompt,
        "idempotency_key": idempotency_key,
        "tags": tags,
    }
    r = requests.post(
        f"{API}/v3/organizations/{ORG}/sessions",
        headers=H,
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_session(session_id: str):
    r = requests.get(
        f"{API}/v3/organizations/{ORG}/sessions/{session_id}",
        headers=H,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def send_message(session_id: str, message: str):
    r = requests.post(
        f"{API}/v3/organizations/{ORG}/sessions/{session_id}/messages",
        headers=H,
        json={"message": message},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
```

**Verify before continuing:** `python -c "from src.devin_client import create_session; print(create_session('echo hello world', 'test-001', ['test']))"`. If endpoint paths differ for your Devin org tier (v1/v2/v3), check the Devin UI "API" tab and adjust the base URL.

### Step 5.7 — Database

`src/db.py`:
```python
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    issue_node_id TEXT PRIMARY KEY,
    issue_number INTEGER,
    issue_title TEXT,
    issue_type TEXT,
    session_id TEXT,
    session_url TEXT,
    status TEXT,
    pr_url TEXT,
    pr_state TEXT,
    acu_consumed REAL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    last_polled_at TEXT
);
"""


@contextmanager
def conn():
    c = sqlite3.connect("data.db")
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.commit()
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
```

### Step 5.8 — Orchestrator

`src/orchestrator.py`:
```python
from pathlib import Path
from datetime import datetime
from src.devin_client import create_session
from src.db import conn

PLAYBOOK_MAP = {
    "security-fix": "security_fix.devin.md",
    "dep-upgrade": "dep_upgrade.devin.md",
    "js-to-ts": "js_to_ts.devin.md",
    "lint-debt": "lint_debt.devin.md",
    "doc-drift": "doc_drift.devin.md",
}


def classify(labels: list[str]) -> str | None:
    for label in labels:
        if label in PLAYBOOK_MAP:
            return label
    return None


def compose_prompt(issue: dict, issue_type: str, repo: str) -> str:
    playbook = Path(f"playbooks/{PLAYBOOK_MAP[issue_type]}").read_text()
    return f"""{playbook}

---

## Task

Repo: {repo}
Issue: #{issue['number']} — {issue['title']}
URL: {issue['html_url']}

## Issue body

{issue['body']}

Follow the playbook above. Open a PR when stop conditions are met.
"""


def dispatch(issue: dict, repo: str):
    issue_type = classify([l["name"] for l in issue["labels"]])
    if not issue_type:
        return None
    prompt = compose_prompt(issue, issue_type, repo)
    session = create_session(
        prompt=prompt,
        idempotency_key=issue["node_id"],
        tags=[issue_type, f"issue-{issue['number']}"],
    )
    with conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO runs
               (issue_node_id, issue_number, issue_title, issue_type,
                session_id, session_url, status, started_at)
               VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (
                issue["node_id"],
                issue["number"],
                issue["title"],
                issue_type,
                session.get("session_id") or session.get("id"),
                session.get("url"),
                datetime.utcnow().isoformat(),
            ),
        )
    return session
```

### Step 5.9 — Webhook receiver

`src/webhook.py`:
```python
import hmac
import hashlib
import os
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from src.orchestrator import dispatch
from src.db import init

app = FastAPI()
SECRET = os.environ.get("GH_WEBHOOK_SECRET", "").encode()


@app.on_event("startup")
def _startup():
    init()


def _verify(body: bytes, sig: str):
    expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig or ""):
        raise HTTPException(401, "bad signature")


@app.post("/webhook")
async def webhook(req: Request, bg: BackgroundTasks):
    body = await req.body()
    if SECRET:
        _verify(body, req.headers.get("x-hub-signature-256"))
    payload = await req.json()
    if req.headers.get("x-github-event") != "issues":
        return {"skipped": True, "reason": "not an issues event"}
    if payload.get("action") not in ("opened", "labeled"):
        return {"skipped": True, "reason": f"action={payload.get('action')}"}
    issue = payload["issue"]
    repo = payload["repository"]["full_name"]
    if not any(l["name"] == "devin-auto" for l in issue["labels"]):
        return {"skipped": True, "reason": "no devin-auto label"}
    bg.add_task(dispatch, issue, repo)
    return {"queued": True, "issue": issue["number"]}
```

### Step 5.10 — Poller

`src/poller.py`:
```python
import time
from datetime import datetime
from src.devin_client import get_session, send_message
from src.db import conn

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "stopped"}


def _ci_failed_summary(session: dict) -> str | None:
    # Adapt to actual Devin response shape after first real session
    pr = session.get("pull_request") or {}
    if pr.get("ci_status") == "failed":
        return pr.get("ci_summary", "CI failed; check logs.")
    return None


def poll_once():
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM runs WHERE status NOT IN ('completed','failed','cancelled','stopped')"
        ).fetchall()

    for row in rows:
        try:
            s = get_session(row["session_id"])
        except Exception as e:
            print(f"poll err for {row['session_id']}: {e}")
            continue

        status = s.get("status_enum") or s.get("status") or "unknown"
        pr_url = (s.get("pull_request") or {}).get("url")
        acu = s.get("acu_consumed", 0)

        with conn() as c:
            c.execute(
                """UPDATE runs SET status=?, pr_url=?, acu_consumed=?, last_polled_at=?
                   WHERE issue_node_id=?""",
                (status, pr_url, acu, datetime.utcnow().isoformat(), row["issue_node_id"]),
            )

        ci_msg = _ci_failed_summary(s)
        if ci_msg and status not in TERMINAL_STATUSES:
            send_message(
                row["session_id"],
                f"CI failed on PR {pr_url}.\n\n{ci_msg}\n\n"
                "Please diagnose and fix. Do not open a new PR — push to the same branch.",
            )


if __name__ == "__main__":
    while True:
        try:
            poll_once()
        except Exception as e:
            print("poll loop err:", e)
        time.sleep(30)
```

### Step 5.11 — Dashboard

`src/dashboard.py`:
```python
import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Tier-3 Remediator", layout="wide")
st.title("Tier-3 Backlog Auto-Remediator")

HOURS_SAVED = {
    "security-fix": 4.0,
    "dep-upgrade": 1.0,
    "js-to-ts": 2.0,
    "lint-debt": 0.5,
    "doc-drift": 0.25,
}

df = pd.read_sql("SELECT * FROM runs", sqlite3.connect("data.db"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Issues processed", len(df))
c2.metric("PRs opened", df["pr_url"].notna().sum())
merged = (df["pr_state"] == "merged").sum()
c3.metric("PRs merged", int(merged))
hours = sum(HOURS_SAVED.get(t, 1.0) for t in df[df["pr_state"] == "merged"]["issue_type"])
c4.metric("Engineer hours saved", f"{hours:.1f}h")

st.subheader("Queue status")
st.dataframe(df[["issue_number", "issue_title", "issue_type", "status", "pr_url"]])

st.subheader("Success rate by issue type")
if len(df):
    by_type = df.groupby("issue_type").agg(
        total=("issue_node_id", "count"),
        succeeded=("pr_state", lambda s: (s == "merged").sum()),
    )
    by_type["rate"] = by_type["succeeded"] / by_type["total"]
    st.bar_chart(by_type["rate"])

st.subheader("Cost per merged PR")
if merged > 0:
    total_acu = df["acu_consumed"].sum()
    st.metric("ACU / merged PR", f"{total_acu / merged:.2f}")
```

### Step 5.12 — Dockerize

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install fastapi uvicorn streamlit pandas requests pyyaml
COPY . .
```

`docker-compose.yml`:
```yaml
services:
  webhook:
    build: .
    command: uvicorn src.webhook:app --host 0.0.0.0 --port 8000
    ports: ["8000:8000"]
    env_file: .env
    volumes: [".:/app"]
  poller:
    build: .
    command: python -m src.poller
    env_file: .env
    volumes: [".:/app"]
  dashboard:
    build: .
    command: streamlit run src/dashboard.py --server.address 0.0.0.0
    ports: ["8501:8501"]
    env_file: .env
    volumes: [".:/app"]
```

### Step 5.13 — Wire up GitHub webhook

In the Superset fork: Settings → Webhooks → Add webhook
- Payload URL: smee.io channel URL
- Content type: `application/json`
- Secret: same as `GH_WEBHOOK_SECRET` in `.env`
- Events: Issues only

Locally:
```bash
npx smee -u https://smee.io/YOUR_CHANNEL -t http://localhost:8000/webhook
docker-compose up
```

### Step 5.14 — Issues to create in the Superset fork

Six issues, GitHub UI. Each with `devin-auto` AND the type label.

| # | Title | Labels |
|---|---|---|
| 1 | `[Security] Add authorization check on dataset ownership transfer endpoint` | `devin-auto`, `security-fix` |
| 2 | `[Deps] Bump urllib3 from 2.5.0 to 2.6.0 (CVE-2025-66471)` | `devin-auto`, `dep-upgrade` |
| 3 | `[Deps] Bump js-yaml 3.14.1 → 3.14.2 (prototype pollution)` | `devin-auto`, `dep-upgrade` |
| 4 | `[Migration] Convert <pick small .js file> to TypeScript` | `devin-auto`, `js-to-ts` |
| 5 | `[Lint] Fix mypy errors in superset/charts/<file>.py` | `devin-auto`, `lint-debt` |
| 6 | `[Docs] Update outdated dev setup commands in CONTRIBUTING.md` | `devin-auto`, `doc-drift` |

Each issue body uses this template:
```
## Context
<2-3 sentences>

## Acceptance criteria
- [ ] Verifiable criterion 1
- [ ] Verifiable criterion 2
- [ ] All tests pass: <exact command>
- [ ] Pre-commit passes: `pre-commit run --all-files`

## Out of scope
- No unrelated refactors
- No formatting changes outside touched files

## Relevant files
- path/to/file1
- path/to/file2
```

### Step 5.15 — Smoke test

End-to-end before relying on the system:
1. Create issue #6 (lowest stakes — docs)
2. Confirm `npx smee` log shows the POST forwarded
3. Confirm webhook receiver logs `{"queued": true}`
4. Confirm a row appears in `data.db` (run `sqlite3 data.db "SELECT * FROM runs"`)
5. Confirm a new session appears in Devin UI
6. Wait for completion, confirm PR opened

If any step fails, fix before continuing.

---

## 6. Playbook Contents (full)

### `playbooks/security_fix.devin.md`

```markdown
# Security Fix

## Workflow
1. Locate the vulnerable code path. Read surrounding context.
2. Write a regression test that FAILS on current code.
3. Apply the minimal fix.
4. Confirm the test now passes.
5. Run `pytest tests/unit_tests/security/` and `pre-commit run --all-files`.

## Stop conditions (ALL must hold)
- Regression test exists and would fail on pre-fix code
- All security tests pass
- pre-commit exits 0
- PR title: `[Security] <one-line>`

## PR template
**Vulnerability:** <one paragraph>
**Fix:** <one paragraph>
**Regression test:** <file:line>
**Verification:** pytest passed, pre-commit passed

## Out of scope
No refactoring. No dep upgrades. No formatting changes outside touched files.
```

### `playbooks/dep_upgrade.devin.md`

```markdown
# Dependency Upgrade

## Workflow
1. Read `UPDATING.md` and the upstream changelog between current and target version.
2. List breaking changes that affect this codebase. If none, say so explicitly.
3. Update the version in the correct file (`requirements/*.txt` or `superset-frontend/package.json`).
4. If breaking changes exist, update call sites.
5. Run full test suite.
6. Run pre-commit.

## Stop conditions
- Version is updated in lock file too (`package-lock.json` or pip-compile output)
- All tests pass
- pre-commit exits 0
- PR description lists breaking changes found (or "none")
- PR title: `[Deps] Bump <name> <old> → <new>`

## Out of scope
No unrelated upgrades. No refactoring. If tests break in ways unrelated to the upgrade, document but don't fix.
```

### `playbooks/js_to_ts.devin.md`

```markdown
# JavaScript to TypeScript Migration

## Workflow
1. Read the target `.js` file fully.
2. Rename to `.ts` (or `.tsx` if it contains JSX).
3. Add explicit types. Use `unknown` not `any` when uncertain.
4. Update imports across the codebase if extension matters.
5. Run `cd superset-frontend && npm run type` and `npm test`.

## Stop conditions
- File compiles with no TS errors
- All existing tests still pass — behavior is unchanged
- No `any` introduced (use `unknown` if truly unknown)
- PR title: `[Migration] Convert <file> to TypeScript`

## Out of scope
No behavioral changes. No refactoring. No additional features.
```

### `playbooks/lint_debt.devin.md`

```markdown
# Lint Debt Fix

## Workflow
1. Run the failing linter on the target file to see exact violations.
2. Fix each violation. No logic changes.
3. Re-run the linter — must exit 0 on the target file.
4. Run the full test suite on affected modules.

## Stop conditions
- Linter exits 0 on the target file
- All tests in affected modules pass
- No behavioral changes
- PR title: `[Lint] Fix <linter> violations in <file>`

## Out of scope
No fixes outside the target file. No refactoring. No formatting changes that aren't lint-driven.
```

### `playbooks/doc_drift.devin.md`

```markdown
# Doc Drift Fix

## Workflow
1. Read the doc section flagged in the issue.
2. Verify the current state by actually running the commands described.
3. Update doc to match what actually works.
4. Run any in-doc code blocks to confirm they work.

## Stop conditions
- Updated commands have been executed and succeeded
- No content removed that's still accurate
- PR title: `[Docs] Update <section> in <file>`

## Out of scope
No formatting overhauls. No reorganization. Only the drifted content.
```

---

## 7. Knowledge Entries (full)

`knowledge/superset_knowledge.yaml`:

```yaml
- name: superset-test-commands
  trigger: When running or verifying tests in apache/superset
  body: |
    Python: pytest tests/unit_tests/
    Frontend: cd superset-frontend && npm test
    Before declaring done, always run pre-commit run --all-files.

- name: superset-branch-conventions
  trigger: When creating a branch or PR for apache/superset
  body: |
    Branch: devin/<issue-number>-<slug>
    PR title prefix matches issue label: [Security], [Deps], [Migration], [Lint], [Docs]
    Never push to master.

- name: superset-security-conventions
  trigger: When fixing security vulnerabilities in apache/superset
  body: |
    Authorization logic: superset/security/manager.py
    API decorators: superset/views/base_api.py
    Security tests: tests/unit_tests/security/
    Always add a regression test that fails on pre-fix code.

- name: superset-dep-upgrade-protocol
  trigger: When upgrading a Python or npm dependency in apache/superset
  body: |
    Python deps: requirements/*.txt
    JS deps: superset-frontend/package.json
    Check UPDATING.md and upstream changelog for breaking changes before upgrading.
    Run full test suite after.
```

---

## 8. Session Prompt Composition

This is what the orchestrator produces for every session. Keep it short — Knowledge + Playbook do the work.

```
<contents of playbooks/{type}.devin.md>

---

## Task

Repo: {owner}/{repo}
Issue: #{number} — {title}
URL: {html_url}

## Issue body

{body}

Follow the playbook above. Open a PR when stop conditions are met.
```

Three responsibilities of the per-session prompt:
1. Pin the playbook at the top
2. Provide issue context
3. Close with "follow the playbook"

---

## 9. Three Critical Automation Patterns

### Idempotency
Every `create_session` call uses `idempotency_key = issue.node_id`. GitHub retries webhooks on 5xx — this guarantees no duplicate sessions.

### Follow-up on CI failure
When the poller sees a session reach `blocked` status OR a PR with failing CI, it sends a follow-up message **to the existing session** (not a new one):

```python
send_message(
    session_id,
    f"CI failed on PR {pr_url}.\n\n{ci_failure_summary}\n\n"
    "Please diagnose and fix. Do not open a new PR — push to the same branch.",
)
```

This is the single most powerful pattern in the Devin API. It converts a one-shot agent into a closed loop.

### Polling cadence
Every 30s for active sessions. Stop polling once `status` is terminal: `completed`, `failed`, `cancelled`, `stopped`. Pull PR state from GitHub API separately — Devin's session view of PR state lags.

---

## 10. Running the System

```bash
cp .env.example .env
# fill in DEVIN_API_KEY, DEVIN_ORG_ID, GH_WEBHOOK_SECRET

python scripts/setup_knowledge.py
docker-compose up
npx smee -u https://smee.io/YOUR_CHANNEL -t http://localhost:8000/webhook
```

Then create an issue with the `devin-auto` label in the Superset fork.

Dashboard: http://localhost:8501

---

## 11. What NOT to Do

- Don't write huge session prompts — push context into Knowledge/Playbooks
- Don't create a new session on CI failure — send a follow-up message to the existing one
- Don't poll without a terminal-status check — you'll burn API quota
- Don't skip idempotency keys — webhook retries will duplicate work
- Don't fabricate dashboard metrics — pull real data from SQLite + Devin metrics API
- Don't skip the smoke test (Step 5.15) — discovering API issues at the end is the #1 cause of submission failure

---

## 12. Acceptance Criteria for This Build

- `docker-compose up` brings up webhook, poller, dashboard cleanly
- Creating a GitHub issue with `devin-auto` label triggers a Devin session within 5 seconds
- Dashboard shows real-time status from SQLite
- At least one merged PR exists from a Devin session before submission
- All 5 playbooks and 4 knowledge entries are committed and pushed
- README in the final repo includes architecture diagram, run instructions, harness design notes, and next-steps section
