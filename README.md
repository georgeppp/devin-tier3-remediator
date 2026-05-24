# Tier-3 Backlog Auto-Remediator

Event-driven automation that uses the [Devin API](https://docs.devin.ai/api-reference/overview) to remediate engineering backlog issues in a forked [Apache Superset](https://github.com/apache/superset) repo.

A GitHub issue labeled `devin-auto` triggers a webhook, which classifies the issue, composes a short session prompt from the matching playbook, and creates a Devin session via the v3 API. A poller watches the session and follows up on CI failures by posting back to the **same** session.

## Architecture

```
┌──────────────────────┐
│  GitHub issue with   │
│  `devin-auto` label  │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ FastAPI webhook      │   verifies HMAC,
│ (src/webhook.py)     │   enqueues background task
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ Orchestrator         │   classify by label
│ (src/orchestrator.py)│   load playbook
│                      │   compose short prompt
│                      │   POST /v3/.../sessions
└──────────┬───────────┘                       with idempotency_key = issue.node_id
           ▼
┌──────────────────────┐
│ Devin Session        │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ Poller (every 30s)   │   GET /v3/.../sessions/{id}
│ (src/poller.py)      │   cross-check PR + CI via GitHub API
│                      │   on CI fail → POST follow-up to SAME session
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ Streamlit dashboard  │   queue, success rate, ACU cost, hours saved
│ (src/dashboard.py)   │
└──────────────────────┘
```

## Devin harness primitives in use

| Layer | Where it lives | How we use it |
|---|---|---|
| **Knowledge** | [`knowledge/superset_knowledge.yaml`](knowledge/superset_knowledge.yaml), uploaded once via [`scripts/setup_knowledge.py`](scripts/setup_knowledge.py) | 4 entries Devin auto-recalls when conditions match (test commands, branch conventions, security/dep protocols) |
| **Playbooks** | [`playbooks/*.devin.md`](playbooks/) — 5 task-type templates | Pinned to the top of every session prompt; defines Workflow → Stop Conditions → PR template → Out-of-scope |
| **Snapshots** | Set up once per repo in the Devin UI (Settings → Repositories) | Cached VM state so each session starts with deps installed |
| **Sessions** | Created per issue via [`src/devin_client.py`](src/devin_client.py) | One session = one issue lifecycle, identified by `idempotency_key = issue.node_id` |

**Composition rule:** anything you'd say to *every* Devin → Knowledge. Anything you'd say to *every Devin doing task X* → Playbook. Anything specific to *this* issue → session prompt. Session prompts stay short.

## Repo layout

```
.
├── src/
│   ├── webhook.py          # FastAPI receiver, HMAC verify, background dispatch
│   ├── orchestrator.py     # label classifier, prompt composer, session creator
│   ├── devin_client.py     # thin v3 API wrapper (sessions, messages, knowledge/notes)
│   ├── poller.py           # 30s polling loop, CI-failure follow-up
│   ├── db.py               # SQLite schema + connection helper
│   └── dashboard.py        # Streamlit dashboard
├── playbooks/              # 5 .devin.md files (security, dep, ts, lint, doc)
├── knowledge/
│   └── superset_knowledge.yaml
├── scripts/
│   └── setup_knowledge.py  # one-time upload of YAML to Devin
├── tests/test_orchestrator.py
├── docker-compose.yml      # webhook + poller + dashboard
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## Running it

### 1. Prerequisites

- Python 3.12+
- Docker + Docker Compose
- A Devin org with a **service-user API key** (`cog_...`, not the `apk_user_...` personal key — only the service-user form works on `/v3/organizations/...`)
- A GitHub fork of `apache/superset`, onboarded in the Devin UI (Settings → Repositories → Add fork URL → save snapshot)
- A [smee.io](https://smee.io) channel for local webhook forwarding (visit `https://smee.io/new`)

### 2. Configure

```bash
cp .env.example .env
# Fill in:
#   DEVIN_API_KEY=cog_...
#   DEVIN_ORG_ID=org-...
#   GH_WEBHOOK_SECRET=<random 32-byte hex>
#   GH_TOKEN=<optional GitHub PAT for PR/CI cross-checks>
#   GH_REPO=<your-user>/superset
```

### 3. One-time setup

```bash
# Upload knowledge entries to the org (4 entries, idempotent — re-running creates duplicates)
python scripts/setup_knowledge.py
```

Verify they appear in the Devin UI under **Knowledge**.

### 4. Start the services

```bash
docker-compose up --build
```

Brings up three services:
- `webhook` on `:8000` — receives GitHub webhooks
- `poller` — long-running, polls active sessions every 30s
- `dashboard` on `:8501` — Streamlit UI

### 5. Forward GitHub webhooks to localhost

```bash
npx smee -u https://smee.io/YOUR_CHANNEL -t http://localhost:8000/webhook
```

In your Superset fork's **Settings → Webhooks → Add webhook**:
- Payload URL: `https://smee.io/YOUR_CHANNEL`
- Content type: `application/json`
- Secret: same as `GH_WEBHOOK_SECRET` in `.env`
- Events: **Issues only**

### 6. Trigger a run

Create an issue in the fork with two labels: `devin-auto` and one of `security-fix`, `dep-upgrade`, `js-to-ts`, `lint-debt`, `doc-drift`.

Open the dashboard at `http://localhost:8501` to watch it process.

## Three automation patterns

### Idempotency
Every `create_session` call uses `idempotency_key = issue.node_id`. GitHub retries webhooks on 5xx — this guarantees no duplicate sessions for the same issue. See [src/orchestrator.py](src/orchestrator.py).

### Follow-up on CI failure (the key Devin primitive)
The poller pulls PR + CI state from the GitHub API. If a session has produced a PR with failing CI **and the session is still active**, it sends a follow-up message to the **same** session — not a new one:

```python
send_message(
    session_id,
    f"CI failed on PR {pr_url}.\n\n{ci_summary}\n\n"
    "Please diagnose and fix. Do not open a new PR — push to the same branch.",
)
```

We de-duplicate by hashing the CI summary so we don't spam the session if it's already working on the same failure. See [src/poller.py](src/poller.py).

### Polling cadence
30s for active sessions only; we stop polling once status is terminal (`completed`/`failed`/`cancelled`/`stopped`/`expired`). PR state is pulled from GitHub directly because Devin's session-side view of PR state lags.

## Issues to create in the fork (Step 5.14)

Six issues, each with `devin-auto` plus a type label:

| # | Title | Labels |
|---|---|---|
| 1 | `[Security] Add authorization check on dataset ownership transfer endpoint` | `devin-auto`, `security-fix` |
| 2 | `[Deps] Bump urllib3 from 2.5.0 to 2.6.0 (CVE-2025-66471)` | `devin-auto`, `dep-upgrade` |
| 3 | `[Deps] Bump js-yaml 3.14.1 → 3.14.2 (prototype pollution)` | `devin-auto`, `dep-upgrade` |
| 4 | `[Migration] Convert <small .js file> to TypeScript` | `devin-auto`, `js-to-ts` |
| 5 | `[Lint] Fix mypy errors in superset/charts/<file>.py` | `devin-auto`, `lint-debt` |
| 6 | `[Docs] Update outdated dev setup commands in CONTRIBUTING.md` | `devin-auto`, `doc-drift` |

Issue body template:

```markdown
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

## Tests

```bash
python -m pytest tests/ -v
```

Covers label classification and prompt composition. The Devin API is not mocked — for that, run a real session via `scripts/setup_knowledge.py` pattern.

## Design notes

- **Why FastAPI + background tasks rather than a proper queue?** GitHub gives webhooks 10s to return. Background tasks are sufficient at this scale (≤6 issues at a time); upgrade to RQ or Celery if you need durability across restarts.
- **Why SQLite?** Single-host deployment with one writer (poller) and one reader (dashboard). Postgres would be overkill.
- **Why poll instead of webhooks-from-Devin?** Devin webhook delivery is available but adds a second public-endpoint dependency. Polling is simpler and 30s latency is fine for human-timescale code changes.
- **Why hash the CI summary for dedup?** Without this, every 30s tick would send the same "CI failed" message until the session pushed a new commit.

## Next steps

- Add Devin **consumption** dashboard integration (`/v3/.../consumption/cycles` and `/v3/.../metrics/*`) for real ACU spend instead of the heuristic
- Replace the polling loop with Devin webhook delivery (signed events from Devin → our `/webhook` on a separate path)
- Auto-close issues when the linked PR merges
- Capacity guardrails: cap parallel sessions per label type
- Add a manual-retry button in the dashboard that re-dispatches a session for a failed run

## What NOT to do

- Don't write huge session prompts — push context into Knowledge/Playbooks
- Don't create a new session on CI failure — follow up on the existing one
- Don't poll without a terminal-status check — burns API quota
- Don't skip idempotency keys — webhook retries will duplicate work
- Don't fabricate dashboard metrics — pull real data from SQLite + Devin metrics API
