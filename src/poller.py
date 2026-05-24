"""Polls active Devin sessions every 30s and closes the loop on CI failures.

Pattern: when a session has produced a PR whose CI is failing AND the session
is still active (i.e. it can receive instructions), we POST a follow-up message
to the SAME session rather than starting a new one. This is the key Devin
harness primitive that converts a one-shot agent into a closed loop.
"""
import hashlib
import os
import time
from datetime import datetime

import requests

from src.db import conn
from src.devin_client import get_session, send_message

TERMINAL_STATUSES = {"completed", "finished", "failed", "cancelled", "stopped", "expired"}
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SEC", "30"))

GH_TOKEN = os.environ.get("GH_TOKEN", "")
_GH_HEADERS = {"Accept": "application/vnd.github+json"}
if GH_TOKEN:
    _GH_HEADERS["Authorization"] = f"Bearer {GH_TOKEN}"


def _normalize_status(session: dict) -> str:
    return (
        session.get("status_enum")
        or session.get("status")
        or session.get("state")
        or "unknown"
    ).lower()


def _extract_pr_url(session: dict) -> str | None:
    pr = session.get("pull_request") or {}
    if isinstance(pr, dict):
        url = pr.get("url") or pr.get("html_url")
        if url:
            return url
    # Some responses surface PRs under output.artifacts or similar; check loosely.
    for key in ("pr_url", "pull_request_url"):
        if session.get(key):
            return session[key]
    return None


def _extract_acu(session: dict) -> float:
    for key in ("acu_consumed", "acu", "acu_used", "total_acu"):
        v = session.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _gh_pr_state(pr_url: str) -> tuple[str | None, str | None, str | None]:
    """Return (pr_state, ci_conclusion, ci_summary) using the GitHub API.

    pr_url is expected to look like https://github.com/{owner}/{repo}/pull/{n}.
    Returns Nones when GH_TOKEN is missing or the URL is unparseable.
    """
    if not pr_url or "github.com" not in pr_url:
        return None, None, None
    try:
        # https://github.com/o/r/pull/N  ->  https://api.github.com/repos/o/r/pulls/N
        _, _, _, owner, repo, _, num = pr_url.split("?")[0].rstrip("/").split("/")
    except Exception:
        return None, None, None

    api = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        pr = requests.get(f"{api}/pulls/{num}", headers=_GH_HEADERS, timeout=15).json()
    except Exception as e:  # noqa: BLE001
        print(f"gh pr fetch err: {e}")
        return None, None, None

    if pr.get("merged"):
        pr_state = "merged"
    else:
        pr_state = pr.get("state")  # open / closed

    sha = pr.get("head", {}).get("sha")
    ci_conclusion = None
    ci_summary = None
    if sha:
        try:
            runs = requests.get(
                f"{api}/commits/{sha}/check-runs",
                headers=_GH_HEADERS,
                timeout=15,
            ).json()
            check_runs = runs.get("check_runs", [])
            failed = [r for r in check_runs if r.get("conclusion") == "failure"]
            if failed:
                ci_conclusion = "failed"
                first = failed[0]
                ci_summary = (
                    f"{first.get('name')}: {first.get('output', {}).get('title') or 'failed'}\n"
                    f"{first.get('html_url')}"
                )
            elif check_runs and all(r.get("conclusion") in ("success", "neutral", "skipped") for r in check_runs):
                ci_conclusion = "success"
            elif check_runs:
                ci_conclusion = "pending"
        except Exception as e:  # noqa: BLE001
            print(f"gh checks fetch err: {e}")
    return pr_state, ci_conclusion, ci_summary


def _ci_signature(pr_url: str, ci_summary: str) -> str:
    return hashlib.sha256(f"{pr_url}|{ci_summary}".encode()).hexdigest()[:16]


def poll_once() -> None:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM runs WHERE status NOT IN ('completed','finished','failed','cancelled','stopped','expired')"
        ).fetchall()

    for row in rows:
        sid = row["session_id"]
        if not sid:
            continue
        try:
            s = get_session(sid)
        except Exception as e:  # noqa: BLE001
            print(f"poll err for {sid}: {e}")
            continue

        status = _normalize_status(s)
        pr_url = _extract_pr_url(s) or row["pr_url"]
        acu = _extract_acu(s) or (row["acu_consumed"] or 0)

        pr_state = None
        ci_conclusion = None
        ci_summary = None
        if pr_url:
            pr_state, ci_conclusion, ci_summary = _gh_pr_state(pr_url)

        completed_at = (
            datetime.utcnow().isoformat() if status in TERMINAL_STATUSES else row["completed_at"]
        )

        with conn() as c:
            c.execute(
                """UPDATE runs
                   SET status=?, pr_url=?, pr_state=COALESCE(?, pr_state),
                       acu_consumed=?, last_polled_at=?, completed_at=?
                   WHERE issue_node_id=?""",
                (
                    status,
                    pr_url,
                    pr_state,
                    acu,
                    datetime.utcnow().isoformat(),
                    completed_at,
                    row["issue_node_id"],
                ),
            )

        # CI-failure follow-up: only when active session + failing CI + we haven't
        # already nudged for this exact failure signature.
        if (
            pr_url
            and ci_conclusion == "failed"
            and status not in TERMINAL_STATUSES
            and ci_summary
        ):
            sig = _ci_signature(pr_url, ci_summary)
            if sig != (row["last_ci_signature"] or ""):
                msg = (
                    f"CI failed on PR {pr_url}.\n\n"
                    f"Failing checks:\n{ci_summary}\n\n"
                    "Please diagnose and fix. Do NOT open a new PR — push to the same branch."
                )
                try:
                    send_message(sid, msg)
                    with conn() as c:
                        c.execute(
                            "UPDATE runs SET follow_ups_sent=follow_ups_sent+1, last_ci_signature=? WHERE issue_node_id=?",
                            (sig, row["issue_node_id"]),
                        )
                    print(f"sent CI-failure follow-up to session {sid}")
                except Exception as e:  # noqa: BLE001
                    print(f"send_message err for {sid}: {e}")


def main() -> None:
    while True:
        try:
            poll_once()
        except Exception as e:  # noqa: BLE001
            print(f"poll loop err: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
