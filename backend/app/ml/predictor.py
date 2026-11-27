"""O4 Maintenance-Continuity Predictor (scikit-learn LogisticRegression + GradientBoosting comparator)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.analytics.indicators import assert_no_popularity_features
from app.config import settings


O2_FEATURE_NAMES = [
    "top_contributor_share",
    "maintainer_set_size",
    "release_interval_cv",
    "longest_release_gap_months",
    "release_count_12m",
]

O3_FEATURE_NAMES = [
    "contributor_retention",
    "issue_responsiveness_hours",
    "pr_throughput_hours",
    "maintainer_inactivity_slope",
]

ALL_FEATURE_NAMES = O2_FEATURE_NAMES + O3_FEATURE_NAMES

INDICATOR_LABELS = {
    "top_contributor_share": "Top-Contributor Share (O2)",
    "maintainer_set_size": "Maintainer Set Size (O2)",
    "release_interval_cv": "Release Interval Irregularity CV (O2)",
    "longest_release_gap_months": "Longest Release Gap Months (O2)",
    "release_count_12m": "12-Month Release Count (O2)",
    "contributor_retention": "Contributor Retention (O3)",
    "issue_responsiveness_hours": "Issue Response Time Hours (O3)",
    "pr_throughput_hours": "PR Throughput Hours (O3)",
    "maintainer_inactivity_slope": "Maintainer Activity Slope (O3)",
}

# Direction of healthier maintenance continuity (+1 means higher value increases continuity, -1 means lower is better)
HEALTH_DIRECTION = {
    "top_contributor_share": -1,
    "maintainer_set_size": 1,
    "release_interval_cv": -1,
    "longest_release_gap_months": -1,
    "release_count_12m": 1,
    "contributor_retention": 1,
    "issue_responsiveness_hours": -1,
    "pr_throughput_hours": -1,
    "maintainer_inactivity_slope": 1,
}


def extract_feature_vector(indicators: dict, feature_names: list[str] = ALL_FEATURE_NAMES) -> np.ndarray:
    """Convert indicator dict to numpy feature vector after enforcing popularity exclusion."""
    assert_no_popularity_features(feature_names)
    assert_no_popularity_features(indicators.keys())
    return np.array([float(indicators[name]) for name in feature_names], dtype=float)


@dataclass
class PredictionOutput:
    continuity_score: float
    risk_level: str
    top_contributors: list[dict]
    plain_language_explanation: str
    comparator_score: float


class MaintenanceContinuityPredictor:
    """Predicts 12-month maintenance continuity probability without popularity signals."""

    def __init__(self, seed: int = settings.model_seed) -> None:
        self.seed = seed
        self.primary_pipeline: Pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(C=1.0, max_iter=1000, random_state=self.seed)),
            ]
        )
        self.o2_baseline_pipeline: Pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(C=1.0, max_iter=1000, random_state=self.seed)),
            ]
        )
        self.o3_only_pipeline: Pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(C=1.0, max_iter=1000, random_state=self.seed)),
            ]
        )
        self.gb_comparator: GradientBoostingClassifier = GradientBoostingClassifier(
            n_estimators=60, max_depth=3, random_state=self.seed
        )
        self.is_trained: bool = False

    def fit(self, indicator_rows: list[dict], labels: list[int]) -> None:
        """
        Train primary (O2+O3 LogisticRegression), O2-only baseline, O3-only ablation, and GB comparator.

        labels: 1 = active/maintained after 12m horizon, 0 = stalled.
        """
        if len(indicator_rows) < 4 or len(set(labels)) < 2:
            raise ValueError("Need at least 4 labelled projects across both active and stalled classes to fit.")

        X_all = np.vstack([extract_feature_vector(row, ALL_FEATURE_NAMES) for row in indicator_rows])
        X_o2 = np.vstack([extract_feature_vector(row, O2_FEATURE_NAMES) for row in indicator_rows])
        X_o3 = np.vstack([extract_feature_vector(row, O3_FEATURE_NAMES) for row in indicator_rows])
        y = np.array(labels, dtype=int)

        self.primary_pipeline.fit(X_all, y)
        self.o2_baseline_pipeline.fit(X_o2, y)
        self.o3_only_pipeline.fit(X_o3, y)
        self.gb_comparator.fit(X_all, y)
        self.is_trained = True

    def predict(self, indicators: dict) -> PredictionOutput:
        """Return calibrated continuity probability, risk tier, and top 3 contributing indicators."""
        if not self.is_trained:
            raise RuntimeError("Predictor must be trained on dev partition before inference.")

        x_all = extract_feature_vector(indicators, ALL_FEATURE_NAMES).reshape(1, -1)
        prob_active = float(self.primary_pipeline.predict_proba(x_all)[0, 1])
        gb_prob = float(self.gb_comparator.predict_proba(x_all)[0, 1])

        # Single-maintainer structural guardrail (NT-1 / NT-2)
        single_maintainer_risk = (
            indicators["maintainer_set_size"] <= 1 or indicators["top_contributor_share"] >= 0.78
        )
        if single_maintainer_risk:
            # Cap continuity score under single-maintainer concentration regardless of release cadence
            prob_active = min(prob_active, 0.39)

        if single_maintainer_risk:
            risk_level = "CRITICAL_SINGLE_MAINTAINER"
        elif prob_active >= 0.72:
            risk_level = "LOW_RISK"
        elif prob_active >= 0.45:
            risk_level = "MODERATE_RISK"
        else:
            risk_level = "HIGH_RISK"

        scaler: StandardScaler = self.primary_pipeline.named_steps["scaler"]
        clf: LogisticRegression = self.primary_pipeline.named_steps["clf"]
        z = scaler.transform(x_all)[0]
        coefs = clf.coef_[0]

        contributions = []
        for idx, name in enumerate(ALL_FEATURE_NAMES):
            contrib = float(coefs[idx] * z[idx])
            val = float(indicators[name])
            impact = "positive" if contrib >= 0 else "risk"
            contributions.append(
                {
                    "indicator": name,
                    "label": INDICATOR_LABELS[name],
                    "value": round(val, 4),
                    "impact": impact,
                    "contribution_weight": round(contrib, 4),
                    "detail": _describe_indicator(name, val, impact),
                }
            )

        contributions.sort(key=lambda item: abs(item["contribution_weight"]), reverse=True)
        top_3 = contributions[:3]

        explanation = _build_explanation(prob_active, risk_level, indicators, top_3, single_maintainer_risk)

        return PredictionOutput(
            continuity_score=round(prob_active, 4),
            risk_level=risk_level,
            top_contributors=top_3,
            plain_language_explanation=explanation,
            comparator_score=round(gb_prob, 4),
        )

    def predict_o2_only(self, indicators: dict) -> float:
        x_o2 = extract_feature_vector(indicators, O2_FEATURE_NAMES).reshape(1, -1)
        return float(self.o2_baseline_pipeline.predict_proba(x_o2)[0, 1])

    def predict_o3_only(self, indicators: dict) -> float:
        x_o3 = extract_feature_vector(indicators, O3_FEATURE_NAMES).reshape(1, -1)
        return float(self.o3_only_pipeline.predict_proba(x_o3)[0, 1])


def _describe_indicator(name: str, val: float, impact: str) -> str:
    if name == "top_contributor_share":
        pct = round(val * 100, 1)
        return f"Top author holds {pct}% of recent commits ({'concentration risk' if val >= 0.65 else 'healthy distribution'})."
    if name == "maintainer_set_size":
        return f"{int(val)} author(s) account for 50% of commits."
    if name == "contributor_retention":
        return f"{round(val * 100, 1)}% of prior-year contributors remain active."
    if name == "issue_responsiveness_hours":
        return f"Median first response to issues is {round(val, 1)} hours."
    if name == "pr_throughput_hours":
        return f"Median PR merge/close latency is {round(val, 1)} hours."
    if name == "maintainer_inactivity_slope":
        trend = "declining" if val < -0.05 else ("growing" if val > 0.05 else "steady")
        return f"Monthly active maintainer trend is {trend} (slope {round(val, 3)})."
    if name == "release_interval_cv":
        return f"Release interval coefficient of variation is {round(val, 2)}."
    if name == "longest_release_gap_months":
        return f"Longest release gap in observation window is {round(val, 1)} months."
    return f"{int(val)} releases recorded in the last 12 months."


def _build_explanation(
    score: float,
    risk_level: str,
    indicators: dict,
    top_3: list[dict],
    single_maintainer: bool,
) -> str:
    pct = round(score * 100, 1)
    drivers = "; ".join(item["detail"] for item in top_3)
    if single_maintainer:
        return (
            f"Adoption risk is CRITICAL (12-month continuity {pct}%): "
            f"a single maintainer controls {round(indicators['top_contributor_share'] * 100, 1)}% of commits "
            f"(maintainer set size = {indicators['maintainer_set_size']}). "
            f"Popularity and release cadence do not mitigate single-point-of-failure maintenance risk. "
            f"Key drivers: {drivers}"
        )
    return (
        f"12-month maintenance continuity probability is {pct}% ({risk_level.replace('_', ' ')}). "
        f"Assessment excludes repository stars, forks, and downloads by design. "
        f"Top drivers: {drivers}"
    )


predictor = MaintenanceContinuityPredictor()
