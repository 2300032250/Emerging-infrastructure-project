"""O2 Reproducible Reference Pipeline: maintainer distribution & release history (FR-2, Section 4.1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pandas as pd


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_o2_reference(
    commits: Iterable[dict],
    releases: Iterable[dict],
    bot_contributor_ids: set[str],
    cutoff_dt: datetime,
    window_months: int = 12,
) -> dict:
    """
    Compute the O2 baseline indicators on a 12-month observation window ending at cutoff_dt.

    Indicators:
      - top_contributor_share: share of non-bot commits by the most active author
      - maintainer_set_size: smallest number of authors covering >= 50% of commits
      - release_interval_cv: coefficient of variation of inter-release intervals
      - longest_release_gap_months: longest gap between releases (or since last release) in months
      - release_count_12m: number of releases in window
      - commits_12m: total non-bot commits in window
      - truck_factor_estimate: ablation comparator (authors covering 80% of commits)
    """
    cutoff = _ensure_utc(cutoff_dt)
    window_start = cutoff - timedelta(days=30 * window_months)

    commit_rows = [
        {
            "contributor_id": c["contributor_id"],
            "committed_at": _ensure_utc(c["committed_at"]),
        }
        for c in commits
        if c["contributor_id"] not in bot_contributor_ids
        and window_start <= _ensure_utc(c["committed_at"]) <= cutoff
    ]

    if commit_rows:
        df_c = pd.DataFrame(commit_rows)
        counts = df_c["contributor_id"].value_counts().sort_values(ascending=False)
        total_commits = int(counts.sum())
        top_share = float(counts.iloc[0] / total_commits)

        cumulative = counts.cumsum()
        half_threshold = 0.5 * total_commits
        maintainer_set_size = int((cumulative < half_threshold).sum() + 1)

        eighty_threshold = 0.8 * total_commits
        truck_factor = int((cumulative < eighty_threshold).sum() + 1)
    else:
        total_commits = 0
        top_share = 1.0
        maintainer_set_size = 0
        truck_factor = 0

    release_dates = sorted(
        _ensure_utc(r["published_at"])
        for r in releases
        if window_start <= _ensure_utc(r["published_at"]) <= cutoff
    )
    release_count = len(release_dates)

    if release_count >= 2:
        intervals_days = np.array(
            [(release_dates[i] - release_dates[i - 1]).total_seconds() / 86400.0 for i in range(1, release_count)],
            dtype=float,
        )
        mean_interval = float(np.mean(intervals_days))
        std_interval = float(np.std(intervals_days))
        release_cv = float(std_interval / mean_interval) if mean_interval > 0 else 0.0

        tail_gap_days = (cutoff - release_dates[-1]).total_seconds() / 86400.0
        head_gap_days = (release_dates[0] - window_start).total_seconds() / 86400.0
        longest_gap_days = float(max(np.max(intervals_days), tail_gap_days, head_gap_days))
    elif release_count == 1:
        tail_gap_days = (cutoff - release_dates[0]).total_seconds() / 86400.0
        head_gap_days = (release_dates[0] - window_start).total_seconds() / 86400.0
        longest_gap_days = float(max(tail_gap_days, head_gap_days))
        release_cv = 1.25
    else:
        longest_gap_days = float(30 * window_months)
        release_cv = 2.0

    longest_gap_months = round(longest_gap_days / 30.0, 2)

    return {
        "top_contributor_share": round(top_share, 4),
        "maintainer_set_size": maintainer_set_size,
        "release_interval_cv": round(release_cv, 4),
        "longest_release_gap_months": longest_gap_months,
        "release_count_12m": release_count,
        "commits_12m": total_commits,
        "truck_factor_estimate": truck_factor,
    }
