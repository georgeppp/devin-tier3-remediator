"""Classify GitHub issues, compose prompts, and dispatch Devin sessions."""
from datetime import datetime
from pathlib import Path

from src.db import conn
from src.devin_client import create_session

PLAYBOOK_DIR = Path(__file__).resolve().parents[1] / "playbooks"

PLAYBOOK_MAP = {
    "security-fix": "security_fix.devin.md",
    "dep-upgrade": "dep_upgrade.devin.md",
    "js-to-ts": "js_to_ts.devin.md",
    "lint-debt": "lint_debt.devin.md",
    "doc-drift": "doc_drift.devin.md",
}


def classify(labels: list[str]) -> str | None:
    """Return the issue-type label if one of the known playbooks matches."""
    for label in labels:
        if label in PLAYBOOK_MAP:
            return label
    return None


def compose_prompt(issue: dict, issue_type: str, repo: str) -> str:
    playbook = (PLAYBOOK_DIR / PLAYBOOK_MAP[issue_type]).read_text()
    body = issue.get("body") or "(no body provided)"
    return f"""{playbook}

---

## Task

Repo: {repo}
Issue: #{issue['number']} — {issue['title']}
URL: {issue['html_url']}

## Issue body

{body}

Follow the playbook above. Open a PR when stop conditions are met.
"""


def dispatch(issue: dict, repo: str):
    """Classify, compose, create the session, persist the row."""
    issue_type = classify([l["name"] for l in issue.get("labels", [])])
    if not issue_type:
        print(f"skip issue #{issue.get('number')}: no playbook label")
        return None

    prompt = compose_prompt(issue, issue_type, repo)
    session = create_session(
        prompt=prompt,
        idempotency_key=issue["node_id"],
        tags=[issue_type, f"issue-{issue['number']}", repo],
        title=f"[{issue_type}] {issue['title']}",
    )

    session_id = session.get("session_id") or session.get("id")
    session_url = session.get("url") or session.get("session_url")

    with conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO runs
               (issue_node_id, issue_number, issue_title, issue_type, repo,
                session_id, session_url, status, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)""",
            (
                issue["node_id"],
                issue["number"],
                issue["title"],
                issue_type,
                repo,
                session_id,
                session_url,
                datetime.utcnow().isoformat(),
            ),
        )
    print(f"dispatched issue #{issue['number']} -> session {session_id}")
    return session
