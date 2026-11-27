"""Independent pure-Python expected-result oracle for O2 verification (FR-2, Section 6.1)."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def compute_o2_oracle(
    commits: Iterable[dict],
    releases: Iterable[dict],
    bot_contributor_ids: set[str],
    cutoff_dt: datetime,
    window_months: int = 12,
) -> dict:
    """Independent pure-Python implementation (no pandas/numpy) verifying O2 reference output."""
    cutoff = _utc(cutoff_dt)
    start = cutoff - timedelta(days=30 * window_months)

    author_counts: Counter[str] = Counter()
    for item in commits:
        cid = item["contributor_id"]
        ts = _utc(item["committed_at"])
        if cid not in bot_contributor_ids and start <= ts <= cutoff:
            author_counts[cid] += 1

    total = sum(author_counts.values())
    if total == 0:
        top_share = 1.0
        maintainer_set = 0
    else:
        ordered = [cnt for _, cnt in author_counts.most_common()]
        top_share = ordered[0] / total
        running = 0
        maintainer_set = 0
        for cnt in ordered:
            running += cnt
            maintainer_set += 1
            if running >= 0.5 * total:
                break

    rel_dates = sorted(
        _utc(r["published_at"])
        for r in releases
        if start <= _utc(r["published_at"]) <= cutoff
    )
    n_rel = len(rel_dates)
    if n_rel >= 2:
        gaps = [(rel_dates[i] - rel_dates[i - 1]).total_seconds() / 86400.0 for i in range(1, n_rel)]
        mean_g = sum(gaps) / len(gaps)
        var_g = sum((g - mean_g) ** 2 for g in gaps) / len(gaps)
        cv = math.sqrt(var_g) / mean_g if mean_g > 0 else 0.0
        longest = max(
            max(gaps),
            (cutoff - rel_dates[-1]).total_seconds() / 86400.0,
            (rel_dates[0] - start).total_seconds() / 86400.0,
        )
    elif n_rel == 1:
        cv = 1.25
        longest = max(
            (cutoff - rel_dates[0]).total_seconds() / 86400.0,
            (rel_dates[0] - start).total_seconds() / 86400.0,
        )
    else:
        cv = 2.0
        longest = float(30 * window_months)

    return {
        "top_contributor_share": round(top_share, 4),
        "maintainer_set_size": maintainer_set,
        "release_interval_cv": round(cv, 4),
        "longest_release_gap_months": round(longest / 30.0, 2),
        "release_count_12m": n_rel,
        "commits_12m": total,
    }
