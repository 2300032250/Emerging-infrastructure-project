"""Core assessment orchestration: O2 + O3 computation, O4 training/inference, and degraded-mode fallback."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.analytics.indicators import compute_o3_indicators
from app.analytics.reference import compute_o2_reference
from app.config import settings
from app.data.seed_projects import CUTOFF_DT, build_seed_dataset
from app.ingestion.ingestor import ingest_project_payload
from app.ml.predictor import predictor
from app.models import (
    Assessment,
    AuditEvent,
    CommitEvent,
    Contributor,
    IssueEvent,
    Project,
    PullRequestEvent,
    ReleaseEvent,
)
from app.services.telemetry import runtime_state


def compute_project_indicators(
    db: Session,
    project_id: str,
    cutoff_dt: datetime | None = None,
    window_months: int = settings.observation_window_months,
) -> dict:
    """Load persisted repository events and compute O2 + O3 indicators without popularity fields."""
    cutoff = cutoff_dt or datetime.fromisoformat(settings.cutoff_date).replace(tzinfo=timezone.utc)
    if cutoff_dt is None and project_id in {
        p.project_id for p in db.scalars(select(Project).where(Project.partition.in_(["dev", "acceptance"]))).all()
    }:
        cutoff = CUTOFF_DT

    bot_ids = {
        c.contributor_id
        for c in db.scalars(select(Contributor).where(Contributor.is_bot.is_(True))).all()
    }

    commits = [
        {"contributor_id": c.contributor_id, "committed_at": c.committed_at}
        for c in db.scalars(select(CommitEvent).where(CommitEvent.project_id == project_id)).all()
    ]
    releases = [
        {"tag": r.tag, "published_at": r.published_at}
        for r in db.scalars(select(ReleaseEvent).where(ReleaseEvent.project_id == project_id)).all()
    ]
    issues = [
        {
            "opened_at": i.opened_at,
            "first_response_at": i.first_response_at,
            "closed_at": i.closed_at,
        }
        for i in db.scalars(select(IssueEvent).where(IssueEvent.project_id == project_id)).all()
    ]
    prs = [
        {
            "contributor_id": p.contributor_id,
            "opened_at": p.opened_at,
            "closed_at": p.closed_at,
            "merged_at": p.merged_at,
        }
        for p in db.scalars(select(PullRequestEvent).where(PullRequestEvent.project_id == project_id)).all()
    ]

    o2 = compute_o2_reference(commits, releases, bot_ids, cutoff, window_months=window_months)
    o3 = compute_o3_indicators(commits, issues, prs, bot_ids, cutoff, o2_metrics=o2)
    return {**o2, **o3}


def ensure_seeded_and_trained(db: Session) -> None:
    """Seed the dev & acceptance repository partitions if empty and train O4 on the dev partition only."""
    existing_count = db.query(Project).count()
    if existing_count == 0:
        for item in build_seed_dataset():
            ingest_project_payload(db, item, partition=item["partition"])

    if not predictor.is_trained:
        dev_projects = db.scalars(
            select(Project).where(Project.partition == "dev", Project.ground_truth_label.is_not(None))
        ).all()
        rows: list[dict] = []
        labels: list[int] = []
        for proj in dev_projects:
            ind = compute_project_indicators(db, proj.project_id, cutoff_dt=CUTOFF_DT)
            rows.append(ind)
            labels.append(1 if proj.ground_truth_label == "active" else 0)
        if len(rows) >= 4 and len(set(labels)) == 2:
            predictor.fit(rows, labels)


def run_assessment(
    db: Session,
    project_id: str,
    cutoff_dt: datetime | None = None,
    actor_role: str = "decision_maker",
) -> dict:
    """Run O2+O3+O4 assessment or return stale-marked fallback when degraded mode is active."""
    t0 = time.perf_counter()
    ensure_seeded_and_trained(db)

    project = db.get(Project, project_id)
    if project is None:
        runtime_state.record_error()
        raise KeyError(f"Project '{project_id}' not found.")

    if runtime_state.degraded_mode:
        latest = db.scalar(
            select(Assessment)
            .where(Assessment.project_id == project_id)
            .order_by(desc(Assessment.created_at))
        )
        if latest is None:
            runtime_state.record_error()
            raise RuntimeError("Degraded mode active and no prior assessment exists for fallback.")
        return _format_assessment_response(
            latest,
            project,
            is_stale=True,
            stale_reason=f"Degraded mode active ({runtime_state.active_fault or 'upstream fault'}): serving last verified assessment.",
        )

    effective_cutoff = cutoff_dt
    if effective_cutoff is None:
        effective_cutoff = CUTOFF_DT if project.partition in ("dev", "acceptance") else datetime.now(timezone.utc)

    indicators = compute_project_indicators(db, project_id, cutoff_dt=effective_cutoff)
    pred = predictor.predict(indicators)

    popularity_warning = None
    if project.reported_stars >= 5000 and pred.risk_level in ("CRITICAL_SINGLE_MAINTAINER", "HIGH_RISK"):
        popularity_warning = (
            f"Popularity trap detected (NT-1): {project.reported_stars:,} GitHub stars mask "
            f"{'single-maintainer concentration' if indicators['maintainer_set_size'] <= 1 else 'declining sustainability'}. "
            "Stars were excluded from scoring."
        )

    explanation_blob = {
        "top_contributors": pred.top_contributors,
        "plain_language_explanation": pred.plain_language_explanation,
        "popularity_trap_warning": popularity_warning,
        "comparator_gb_score": pred.comparator_score,
    }

    assessment = Assessment(
        assessment_id=f"asmt-{uuid.uuid4().hex[:12]}",
        project_id=project.project_id,
        input_version=project.source_version,
        config_hash=settings.config_hash,
        indicators=indicators,
        score=pred.continuity_score,
        risk_level=pred.risk_level,
        explanation=explanation_blob,
        is_stale=False,
    )
    db.add(assessment)
    db.add(
        AuditEvent(
            audit_id=f"aud-{uuid.uuid4().hex[:12]}",
            event_type="ASSESSMENT_CREATED",
            actor_role=actor_role,
            project_id=project.project_id,
            config_hash=settings.config_hash,
            detail=(
                f"Assessed {project.repository}: continuity={round(pred.continuity_score * 100, 1)}%, "
                f"risk={pred.risk_level}."
            ),
            metadata_json={"assessment_id": assessment.assessment_id, "input_version": project.source_version},
        )
    )
    db.commit()
    db.refresh(assessment)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    runtime_state.record_assessment(elapsed_ms)

    return _format_assessment_response(assessment, project, is_stale=False, stale_reason=None)


def get_latest_assessment(db: Session, project_id: str) -> dict:
    """Return latest stored assessment (marked stale if degraded mode is active) or compute if none exists."""
    ensure_seeded_and_trained(db)
    project = db.get(Project, project_id)
    if project is None:
        raise KeyError(f"Project '{project_id}' not found.")

    latest = db.scalar(
        select(Assessment)
        .where(Assessment.project_id == project_id)
        .order_by(desc(Assessment.created_at))
    )
    if latest is None:
        return run_assessment(db, project_id)

    stale = runtime_state.degraded_mode or latest.is_stale
    reason = (
        f"Degraded mode active ({runtime_state.active_fault or 'fault'}): showing last valid snapshot."
        if runtime_state.degraded_mode
        else None
    )
    return _format_assessment_response(latest, project, is_stale=stale, stale_reason=reason)


def _format_assessment_response(
    assessment: Assessment,
    project: Project,
    is_stale: bool,
    stale_reason: str | None,
) -> dict:
    expl = assessment.explanation or {}
    return {
        "assessment_id": assessment.assessment_id,
        "project_id": assessment.project_id,
        "repository": project.repository,
        "input_version": assessment.input_version,
        "config_hash": assessment.config_hash,
        "continuity_score": assessment.score,
        "continuity_percent": round(assessment.score * 100.0, 1),
        "risk_level": assessment.risk_level,
        "is_stale": is_stale,
        "stale_reason": stale_reason,
        "popularity_independent": True,
        "popularity_trap_warning": expl.get("popularity_trap_warning"),
        "indicators": assessment.indicators,
        "top_contributors": expl.get("top_contributors", []),
        "plain_language_explanation": expl.get("plain_language_explanation", ""),
        "created_at": assessment.created_at,
    }
