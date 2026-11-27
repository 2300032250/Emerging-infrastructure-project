"""O3 Sustainability Indicators Subsystem — strictly independent of popularity (FR-3, Table 5, NT-1, NT-3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np


FORBIDDEN_POPULARITY_FIELDS: frozenset[str] = frozenset(
    {
        "stars",
        "stargazers_count",
        "reported_stars",
        "forks",
        "forks_count",
        "reported_forks",
        "watchers",
        "watchers_count",
        "downloads",
        "download_count",
        "popularity",
        "popularity_score",
        "popularity_rank",
    }
)


class PopularityGuardError(RuntimeError):
    """Raised if any popularity field enters the O3/O4 feature pipeline (Section 4.4 & 6.1)."""


def assert_no_popularity_features(feature_keys: Iterable[str]) -> None:
    """Guard check failing immediately if a popularity signal enters feature computation."""
    normalized = {k.strip().lower() for k in feature_keys}
    violations = normalized.intersection(FORBIDDEN_POPULARITY_FIELDS)
    if violations:
        raise PopularityGuardError(
            f"NT-1/NT-3 policy violation: popularity fields are forbidden in sustainability features: {sorted(violations)}"
        )


def _ensure_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def compute_rubric_scores(o2: dict, o3: dict) -> tuple[float, float]:
    """
    Compute 0-100 frozen 5-criterion rubric scores (anchors 0, 50, 80, 100) for KPI-2 & KPI-3.

    KPI-2 Maintainer Concentration Score (higher = healthier, less concentrated):
      Criteria:
        1. Non-single-author resilience (1 - top_contributor_share)
        2. Core maintainer set depth (maintainer_set_size)
        3. Year-over-year contributor retention
        4. Maintainer activity trend (non-negative slope)
        5. Active commit volume floor (>= 24 commits/yr)
    """
    top_share = o2["top_contributor_share"]
    m_size = o2["maintainer_set_size"]
    retention = o3["contributor_retention"]
    slope = o3["maintainer_inactivity_slope"]
    commits = o2["commits_12m"]

    c1 = max(0.0, min(1.0, (1.0 - top_share) / 0.70)) * 30.0
    c2 = max(0.0, min(1.0, (m_size - 1) / 4.0)) * 25.0 if m_size > 0 else 0.0
    c3 = max(0.0, min(1.0, retention / 0.75)) * 20.0
    c4 = max(0.0, min(1.0, (slope + 0.5) / 0.75)) * 15.0
    c5 = max(0.0, min(1.0, commits / 48.0)) * 10.0
    maintainer_score = round(min(100.0, max(0.0, c1 + c2 + c3 + c4 + c5)), 2)

    """
    KPI-3 Release Continuity Score (higher = more regular, responsive, sustained releases):
      Criteria:
        1. Release cadence regularity (low CV)
        2. Absence of long release gaps
        3. Minimum annual release cadence (>= 4 releases/yr)
        4. Issue responsiveness (<= 72h target)
        5. PR merge throughput (<= 96h target)
    """
    cv = o2["release_interval_cv"]
    gap_m = o2["longest_release_gap_months"]
    rel_cnt = o2["release_count_12m"]
    issue_h = o3["issue_responsiveness_hours"]
    pr_h = o3["pr_throughput_hours"]

    r1 = max(0.0, min(1.0, 1.0 - (cv / 1.5))) * 25.0
    r2 = max(0.0, min(1.0, 1.0 - (gap_m / 9.0))) * 25.0
    r3 = max(0.0, min(1.0, rel_cnt / 6.0)) * 20.0
    r4 = max(0.0, min(1.0, 1.0 - (issue_h / 336.0))) * 15.0
    r5 = max(0.0, min(1.0, 1.0 - (pr_h / 336.0))) * 15.0
    release_score = round(min(100.0, max(0.0, r1 + r2 + r3 + r4 + r5)), 2)

    return maintainer_score, release_score


def compute_o3_indicators(
    commits: Iterable[dict],
    issues: Iterable[dict],
    prs: Iterable[dict],
    bot_contributor_ids: set[str],
    cutoff_dt: datetime,
    o2_metrics: dict,
    input_keys: Iterable[str] = (),
) -> dict:
    """
    Compute O3 sustainability indicators independent of popularity (Table 5).

    Indicators:
      - contributor_retention: share of prior-year active non-bot contributors active this year
      - issue_responsiveness_hours: median time to first maintainer response on issues
      - pr_throughput_hours: median time from PR open to merge/close
      - maintainer_inactivity_slope: OLS slope of monthly active maintainers over last 12 months
    """
    assert_no_popularity_features(input_keys)

    cutoff = _ensure_utc(cutoff_dt)
    curr_start = cutoff - timedelta(days=360)
    prev_start = cutoff - timedelta(days=720)

    prev_authors: set[str] = set()
    curr_authors: set[str] = set()
    monthly_authors: list[set[str]] = [set() for _ in range(12)]

    for c in commits:
        cid = c["contributor_id"]
        if cid in bot_contributor_ids:
            continue
        ts = _ensure_utc(c["committed_at"])
        if prev_start <= ts < curr_start:
            prev_authors.add(cid)
        elif curr_start <= ts <= cutoff:
            curr_authors.add(cid)
            bucket = min(11, max(0, int((ts - curr_start).total_seconds() // (30 * 86400))))
            monthly_authors[bucket].add(cid)

    if prev_authors:
        retention = len(prev_authors.intersection(curr_authors)) / len(prev_authors)
    else:
        retention = 1.0 if len(curr_authors) >= 3 else 0.25

    issue_latencies: list[float] = []
    for iss in issues:
        opened = _ensure_utc(iss["opened_at"])
        if not (curr_start <= opened <= cutoff):
            continue
        resp = iss.get("first_response_at")
        if resp is not None:
            hours = max(0.1, (_ensure_utc(resp) - opened).total_seconds() / 3600.0)
            issue_latencies.append(min(hours, 720.0))
        else:
            age_hours = max(1.0, (cutoff - opened).total_seconds() / 3600.0)
            issue_latencies.append(min(age_hours, 720.0))

    issue_responsiveness_hours = float(np.median(issue_latencies)) if issue_latencies else 360.0

    pr_latencies: list[float] = []
    for pr in prs:
        if pr["contributor_id"] in bot_contributor_ids:
            continue
        opened = _ensure_utc(pr["opened_at"])
        if not (curr_start <= opened <= cutoff):
            continue
        done = pr.get("merged_at") or pr.get("closed_at")
        if done is not None:
            hours = max(0.1, (_ensure_utc(done) - opened).total_seconds() / 3600.0)
            pr_latencies.append(min(hours, 720.0))
        else:
            age_hours = max(1.0, (cutoff - opened).total_seconds() / 3600.0)
            pr_latencies.append(min(age_hours, 720.0))

    pr_throughput_hours = float(np.median(pr_latencies)) if pr_latencies else 360.0

    x = np.arange(12, dtype=float)
    y = np.array([len(s) for s in monthly_authors], dtype=float)
    if np.std(x) > 0:
        slope = float(np.polyfit(x, y, 1)[0])
    else:
        slope = 0.0

    o3 = {
        "contributor_retention": round(retention, 4),
        "issue_responsiveness_hours": round(issue_responsiveness_hours, 2),
        "pr_throughput_hours": round(pr_throughput_hours, 2),
        "maintainer_inactivity_slope": round(slope, 4),
    }

    maintainer_score, release_score = compute_rubric_scores(o2_metrics, o3)
    o3["maintainer_concentration_score"] = maintainer_score
    o3["release_continuity_score"] = release_score
    return o3
