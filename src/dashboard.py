"""Streamlit dashboard reading from data.db.

Metrics shown:
- Issues processed, PRs opened, PRs merged
- Engineer hours saved (per-type heuristic, configurable below)
- Per-type success rate
- ACU cost per merged PR
"""
import os
import sqlite3

import pandas as pd
import streamlit as st

DB_PATH = os.environ.get("DEVIN_DB_PATH", "data.db")

st.set_page_config(page_title="Tier-3 Backlog Auto-Remediator", layout="wide")
st.title("Tier-3 Backlog Auto-Remediator")
st.caption("Devin-powered: GitHub issue with `devin-auto` label → session → PR")

# Engineer-hours-saved heuristic per issue type. Adjust to taste.
HOURS_SAVED = {
    "security-fix": 4.0,
    "dep-upgrade": 1.0,
    "js-to-ts": 2.0,
    "lint-debt": 0.5,
    "doc-drift": 0.25,
}


@st.cache_data(ttl=10)
def load() -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        try:
            return pd.read_sql("SELECT * FROM runs", conn)
        except Exception:
            return pd.DataFrame()


df = load()

if df.empty:
    st.info("No runs yet. Create a `devin-auto`-labeled issue in the connected repo.")
    st.stop()

# Top-line metrics
c1, c2, c3, c4 = st.columns(4)
c1.metric("Issues processed", len(df))
prs_opened = df["pr_url"].notna().sum()
c2.metric("PRs opened", int(prs_opened))
merged_mask = df["pr_state"] == "merged"
merged = int(merged_mask.sum())
c3.metric("PRs merged", merged)
hours = sum(HOURS_SAVED.get(t, 1.0) for t in df.loc[merged_mask, "issue_type"])
c4.metric("Engineer hours saved", f"{hours:.1f}h")

st.divider()

# Queue
st.subheader("Queue status")
queue_cols = [
    "issue_number", "issue_title", "issue_type", "status",
    "pr_url", "pr_state", "acu_consumed", "follow_ups_sent",
]
queue_cols = [c for c in queue_cols if c in df.columns]
st.dataframe(
    df.sort_values("started_at", ascending=False)[queue_cols],
    use_container_width=True,
    hide_index=True,
)

# Success rate
st.subheader("Success rate by issue type")
if merged:
    by_type = df.groupby("issue_type").agg(
        total=("issue_node_id", "count"),
        succeeded=("pr_state", lambda s: (s == "merged").sum()),
    )
    by_type["rate"] = by_type["succeeded"] / by_type["total"]
    st.bar_chart(by_type["rate"])
else:
    st.caption("No merged PRs yet — success-rate chart hidden until one merges.")

# Cost
st.subheader("Cost per merged PR")
if merged > 0:
    total_acu = df["acu_consumed"].fillna(0).sum()
    st.metric("ACU / merged PR", f"{total_acu / merged:.2f}")
else:
    st.caption("Awaiting first merged PR.")

st.divider()
st.caption(
    "Dashboard auto-refreshes every 10s (cached). DB: "
    f"`{DB_PATH}`"
)
