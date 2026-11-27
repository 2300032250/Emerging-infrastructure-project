"""Pydantic API and domain contracts (FR-4, FR-5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    use_case_id: str
    config_version: str
    config_hash: str
    degraded_mode: bool
    database_connected: bool
    model_trained: bool
    checkpoint_age_seconds: Optional[float]
    total_projects: int
    total_assessments: int


class ProjectSummary(BaseModel):
    project_id: str
    repository: str
    owner: str
    ecosystem: str
    licence: str
    source_version: str
    partition: str
    reported_stars: int
    reported_forks: int
    ground_truth_label: Optional[str] = None
    latest_score: Optional[float] = None
    latest_risk_level: Optional[str] = None
    popularity_mismatch_flag: bool = False


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]
    sort_applied: str
    popularity_sort_overridden: bool = False
    audit_notice: Optional[str] = None


class IngestRequest(BaseModel):
    repository: str = Field(..., description="GitHub owner/repo or repository identifier")
    mode: str = Field(default="auto", description="'auto' | 'github' | 'synthetic_fixture'")
    partition: str = Field(default="live")
    licence: str = Field(default="Apache-2.0")
    source_version: Optional[str] = None


class IngestResponse(BaseModel):
    project_id: str
    repository: str
    source_version: str
    commits_ingested: int
    releases_ingested: int
    issues_ingested: int
    prs_ingested: int
    bots_filtered: int
    aliases_resolved: int
    checkpoint_id: str


class IndicatorBreakdown(BaseModel):
    # O2 Reference
    top_contributor_share: float
    maintainer_set_size: int
    release_interval_cv: float
    longest_release_gap_months: float
    release_count_12m: int
    commits_12m: int
    truck_factor_estimate: int
    # O3 Sustainability (popularity-independent)
    contributor_retention: float
    issue_responsiveness_hours: float
    pr_throughput_hours: float
    maintainer_inactivity_slope: float
    # Frozen 0-100 rubric scores (KPI-2 & KPI-3)
    maintainer_concentration_score: float
    release_continuity_score: float


class ContributingFactor(BaseModel):
    indicator: str
    label: str
    value: float
    impact: str  # 'positive' | 'risk'
    contribution_weight: float
    detail: str


class AssessmentResponse(BaseModel):
    assessment_id: str
    project_id: str
    repository: str
    input_version: str
    config_hash: str
    continuity_score: float
    continuity_percent: float
    risk_level: str
    is_stale: bool
    stale_reason: Optional[str] = None
    popularity_independent: bool = True
    popularity_trap_warning: Optional[str] = None
    indicators: IndicatorBreakdown
    top_contributors: list[ContributingFactor]
    plain_language_explanation: str
    created_at: datetime


class AssessmentRunRequest(BaseModel):
    project_id: str
    cutoff_date: Optional[str] = None


class OperatorStatusResponse(BaseModel):
    degraded_mode: bool
    active_fault: Optional[str]
    config_version: str
    config_hash: str
    total_checkpoints: int
    oldest_checkpoint_age_seconds: Optional[float]
    error_count: int
    nt_guard_triggers: int
    checkpoints: list[dict[str, Any]]


class RecoveryResponse(BaseModel):
    recovered: bool
    replayed_checkpoints: int
    recovery_time_ms: float
    duplicate_records_prevented: int
    degraded_mode: bool
    message: str


class NegativeTestResult(BaseModel):
    test_id: str
    name: str
    condition: str
    fixture_id: str
    passed: bool
    expected_behaviour: str
    observed_behaviour: str
    recovery_time_ms: float
    residual_risk: str
    audit_event_id: str


class NegativeTestCampaignResponse(BaseModel):
    all_passed: bool
    executed_at: datetime
    results: list[NegativeTestResult]


class AuditEventItem(BaseModel):
    audit_id: str
    event_type: str
    actor_role: str
    project_id: Optional[str]
    config_hash: str
    detail: str
    metadata_json: dict[str, Any]
    created_at: datetime
