"""Verify O2 Reference Pipeline matches the independent pure-Python oracle (FR-2, Section 6.1)."""

from datetime import datetime, timedelta, timezone

from app.analytics.oracle import compute_o2_oracle
from app.analytics.reference import compute_o2_reference


def test_o2_reference_matches_independent_oracle():
    cutoff = datetime(2025, 11, 1, tzinfo=timezone.utc)
    bots = {"gh:dependabotbot"}

    commits = [
        {"contributor_id": "alice", "committed_at": cutoff - timedelta(days=10)},
        {"contributor_id": "alice", "committed_at": cutoff - timedelta(days=20)},
        {"contributor_id": "alice", "committed_at": cutoff - timedelta(days=30)},
        {"contributor_id": "bob", "committed_at": cutoff - timedelta(days=40)},
        {"contributor_id": "bob", "committed_at": cutoff - timedelta(days=50)},
        {"contributor_id": "carol", "committed_at": cutoff - timedelta(days=60)},
        {"contributor_id": "gh:dependabotbot", "committed_at": cutoff - timedelta(days=5)},
        {"contributor_id": "old-user", "committed_at": cutoff - timedelta(days=400)},  # outside 12m window
    ]
    releases = [
        {"tag": "v1.0.0", "published_at": cutoff - timedelta(days=200)},
        {"tag": "v1.1.0", "published_at": cutoff - timedelta(days=140)},
        {"tag": "v1.2.0", "published_at": cutoff - timedelta(days=50)},
    ]

    ref = compute_o2_reference(commits, releases, bots, cutoff)
    oracle = compute_o2_oracle(commits, releases, bots, cutoff)

    for key in oracle:
        assert ref[key] == oracle[key], f"Mismatch on {key}: {ref[key]} != {oracle[key]}"
    assert ref["commits_12m"] == 6
    assert ref["top_contributor_share"] == 0.5
    assert ref["maintainer_set_size"] == 1
