"""Guard tests ensuring popularity signals never enter O3 or O4 feature sets (Section 4.4, 6.1, NT-1)."""

from datetime import datetime, timezone

import pytest

from app.analytics.indicators import PopularityGuardError, assert_no_popularity_features, compute_o3_indicators
from app.ml.predictor import ALL_FEATURE_NAMES, O2_FEATURE_NAMES, O3_FEATURE_NAMES, extract_feature_vector


@pytest.mark.parametrize(
    "forbidden_field",
    ["stars", "stargazers_count", "reported_stars", "forks", "downloads", "popularity_rank"],
)
def test_popularity_guard_rejects_popularity_fields(forbidden_field: str):
    with pytest.raises(PopularityGuardError):
        assert_no_popularity_features(["top_contributor_share", forbidden_field])

    with pytest.raises(PopularityGuardError):
        compute_o3_indicators(
            commits=[],
            issues=[],
            prs=[],
            bot_contributor_ids=set(),
            cutoff_dt=datetime(2025, 11, 1, tzinfo=timezone.utc),
            o2_metrics={
                "top_contributor_share": 0.5,
                "maintainer_set_size": 2,
                "release_interval_cv": 0.2,
                "longest_release_gap_months": 1.5,
                "release_count_12m": 6,
                "commits_12m": 50,
            },
            input_keys=[forbidden_field],
        )


def test_predictor_feature_vectors_are_popularity_free():
    assert_no_popularity_features(O2_FEATURE_NAMES)
    assert_no_popularity_features(O3_FEATURE_NAMES)
    assert_no_popularity_features(ALL_FEATURE_NAMES)

    bad_row = {name: 1.0 for name in ALL_FEATURE_NAMES}
    bad_row["stars"] = 50000
    with pytest.raises(PopularityGuardError):
        extract_feature_vector(bad_row)
