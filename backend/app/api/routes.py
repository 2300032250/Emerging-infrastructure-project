"""FastAPI routes for assessments, ingestion, evaluation, operator controls, and security tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.data.seed_projects import _generate_project_fixture
from app.db import get_db
from app.ingestion.github_client import GitHubAPIClient, GitHubAuthError, GitHubRateLimitPaused
from app.ingestion.ingestor import ingest_project_payload
from app.ingestion.validator import ValidationGateError
from app.ml.predictor import predictor
from app.models import Assessment, AuditEvent, Checkpoint, EvidenceManifest, Project
from app.schemas import (
    AssessmentResponse,
    AssessmentRunRequest,
    AuditEventItem,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    NegativeTestCampaignResponse,
    OperatorStatusResponse,
    ProjectListResponse,
    RecoveryResponse,
)
from app.services.assessment_service import ensure_seeded_and_trained, get_latest_assessment, run_assessment
from app.services.evaluation_service import evaluate_acceptance_partition
from app.services.security_service import run_negative_test_campaign
from app.services.telemetry import inject_fault, recover_from_checkpoints, runtime_state


router = APIRouter()


def _require_operator(x_actor_role: str = Header(default="decision_maker")) -> str:
    if x_actor_role.lower() != "operator":
        raise HTTPException(
            status_code=403,
            detail="Role separation (Section 4.6): operator actions require X-Actor-Role: operator.",
        )
    return "operator"


def _oldest_checkpoint_age_seconds(db: Session) -> Optional[float]:
    checkpoints = db.scalars(select(Checkpoint)).all()
    if not checkpoints:
        return None
    now = datetime.now(timezone.utc)
    ages = []
    for cp in checkpoints:
        ts = cp.updated_at.replace(tzinfo=timezone.utc) if cp.updated_at.tzinfo is None else cp.updated_at.astimezone(timezone.utc)
        ages.append(max(0.0, (now - ts).total_seconds()))
    return round(max(ages), 2)


def list_projects_with_sustainability_guard(
    db: Session,
    sort_by: str = "sustainability_desc",
    partition: Optional[str] = None,
) -> dict:
    """List projects sorted by sustainability score; overrides popularity sort requests (NT-3)."""
    ensure_seeded_and_trained(db)

    stmt = select(Project)
    if partition:
        stmt = stmt.where(Project.partition == partition)
    projects = db.scalars(stmt).all()

    popularity_requested = sort_by.lower() in {"stars", "forks", "popularity", "reported_stars"}
    audit_notice = None
    if popularity_requested:
        runtime_state.record_nt_guard()
        audit_notice = (
            f"NT-3 Guard: Requested sort_by='{sort_by}' was overridden with sustainability ranking "
            "and logged to the immutable audit trail."
        )
        db.add(
            AuditEvent(
                audit_id=f"aud-{uuid.uuid4().hex[:12]}",
                event_type="POPULARITY_SORT_OVERRIDDEN",
                actor_role="decision_maker",
                project_id=None,
                config_hash=settings.config_hash,
                detail=audit_notice,
                metadata_json={"requested_sort": sort_by, "enforced_sort": "sustainability_desc"},
            )
        )
        db.commit()

    summaries = []
    for proj in projects:
        latest = db.scalar(
            select(Assessment)
            .where(Assessment.project_id == proj.project_id)
            .order_by(desc(Assessment.created_at))
        )
        if latest is None and not runtime_state.degraded_mode:
            run_assessment(db, proj.project_id, actor_role="system_bootstrap")
            latest = db.scalar(
                select(Assessment)
                .where(Assessment.project_id == proj.project_id)
                .order_by(desc(Assessment.created_at))
            )

        score = latest.score if latest else None
        risk = latest.risk_level if latest else None
        mismatch = bool(
            proj.reported_stars >= 5000 and risk in ("CRITICAL_SINGLE_MAINTAINER", "HIGH_RISK")
        )
        summaries.append(
            {
                "project_id": proj.project_id,
                "repository": proj.repository,
                "owner": proj.owner,
                "ecosystem": proj.ecosystem,
                "licence": proj.licence,
                "source_version": proj.source_version,
                "partition": proj.partition,
                "reported_stars": proj.reported_stars,
                "reported_forks": proj.reported_forks,
                "ground_truth_label": proj.ground_truth_label,
                "latest_score": score,
                "latest_risk_level": risk,
                "popularity_mismatch_flag": mismatch,
            }
        )

    summaries.sort(key=lambda item: (item["latest_score"] if item["latest_score"] is not None else -1.0), reverse=True)

    return {
        "projects": summaries,
        "sort_applied": "sustainability_desc",
        "popularity_sort_overridden": popularity_requested,
        "audit_notice": audit_notice,
    }


@router.get("/health", response_model=HealthResponse, tags=["Operations"])
@router.get("/api/v1/health", response_model=HealthResponse, tags=["Operations"])
def health(db: Session = Depends(get_db)):
    ensure_seeded_and_trained(db)
    return {
        "status": "degraded" if runtime_state.degraded_mode else "healthy",
        "use_case_id": settings.use_case_id,
        "config_version": settings.config_version,
        "config_hash": settings.config_hash,
        "degraded_mode": runtime_state.degraded_mode,
        "database_connected": True,
        "model_trained": predictor.is_trained,
        "checkpoint_age_seconds": _oldest_checkpoint_age_seconds(db),
        "total_projects": db.query(Project).count(),
        "total_assessments": db.query(Assessment).count(),
    }


@router.get("/metrics", tags=["Telemetry"])
def prometheus_metrics(db: Session = Depends(get_db)):
    cp_age = _oldest_checkpoint_age_seconds(db)
    body = runtime_state.render_prometheus(cp_age)
    return Response(content=body, media_type="text/plain; version=0.0.4")


@router.get("/api/v1/projects", response_model=ProjectListResponse, tags=["Decision Maker"])
def list_projects(
    sort_by: str = Query(default="sustainability_desc"),
    partition: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    return list_projects_with_sustainability_guard(db=db, sort_by=sort_by, partition=partition)


@router.post("/api/v1/projects/ingest", response_model=IngestResponse, tags=["Ingestion"])
def ingest_project(req: IngestRequest, db: Session = Depends(get_db)):
    ensure_seeded_and_trained(db)
    try:
        if req.mode == "synthetic_fixture":
            seed_val = sum(ord(ch) for ch in req.repository)
            # Deterministic offline fixture for custom repository evaluation
            healthy = seed_val % 2 == 0
            payload = _generate_project_fixture(
                repository=req.repository,
                licence=req.licence,
                partition=req.partition,
                ground_truth_label="active" if healthy else "stalled",
                reported_stars=4500 if healthy else 18500,
                reported_forks=520 if healthy else 1900,
                maintainer_weights=[0.25, 0.22, 0.20, 0.18, 0.15] if healthy else [0.90, 0.06, 0.04],
                commits_per_month_start=14 if healthy else 11,
                commits_per_month_end=18 if healthy else 2,
                release_days_interval=35 if healthy else 85,
                release_jitter_days=5 if healthy else 25,
                last_release_gap_days=16 if healthy else 140,
                retention_ratio=0.82 if healthy else 0.18,
                median_issue_response_h=16.0 if healthy else 260.0,
                median_pr_merge_h=24.0 if healthy else 340.0,
                seed=seed_val,
            )
            if req.source_version:
                payload["source_version"] = req.source_version
        else:
            client = GitHubAPIClient()
            payload = client.fetch_repository_activity(req.repository)
            if req.source_version:
                payload["source_version"] = req.source_version

        result = ingest_project_payload(db, payload, partition=req.partition)
        run_assessment(db, result["project_id"], actor_role="decision_maker")
        return result
    except GitHubAuthError as exc:
        runtime_state.record_error()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GitHubRateLimitPaused as exc:
        runtime_state.record_error()
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValidationGateError as exc:
        runtime_state.record_error()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        runtime_state.record_error()
        raise HTTPException(status_code=502, detail=f"Ingestion failed: {exc}") from exc


@router.post("/api/v1/assessments/run", response_model=AssessmentResponse, tags=["Decision Maker"])
def create_assessment(req: AssessmentRunRequest, db: Session = Depends(get_db)):
    try:
        cutoff = None
        if req.cutoff_date:
            cutoff = datetime.fromisoformat(req.cutoff_date).replace(tzinfo=timezone.utc)
        return run_assessment(db, req.project_id, cutoff_dt=cutoff, actor_role="decision_maker")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/v1/assessments/{project_id}", response_model=AssessmentResponse, tags=["Decision Maker"])
def get_assessment(project_id: str, db: Session = Depends(get_db)):
    try:
        return get_latest_assessment(db, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/v1/assessments/{project_id}/history", tags=["Decision Maker"])
def get_assessment_history(project_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Assessment)
        .where(Assessment.project_id == project_id)
        .order_by(desc(Assessment.created_at))
    ).all()
    return [
        {
            "assessment_id": r.assessment_id,
            "input_version": r.input_version,
            "config_hash": r.config_hash,
            "score": r.score,
            "risk_level": r.risk_level,
            "is_stale": r.is_stale,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/api/v1/evaluation/summary", tags=["Validation"])
def evaluation_summary(trials: int = Query(default=30, ge=30, le=200), db: Session = Depends(get_db)):
    return evaluate_acceptance_partition(db, trials=trials)


@router.get("/api/v1/operator/status", response_model=OperatorStatusResponse, tags=["Operations"])
def operator_status(
    db: Session = Depends(get_db),
    _: str = Depends(_require_operator),
):
    ensure_seeded_and_trained(db)
    checkpoints = db.scalars(select(Checkpoint).order_by(Checkpoint.project_id)).all()
    return {
        "degraded_mode": runtime_state.degraded_mode,
        "active_fault": runtime_state.active_fault,
        "config_version": settings.config_version,
        "config_hash": settings.config_hash,
        "total_checkpoints": len(checkpoints),
        "oldest_checkpoint_age_seconds": _oldest_checkpoint_age_seconds(db),
        "error_count": runtime_state.errors_total,
        "nt_guard_triggers": runtime_state.nt_guard_triggers_total,
        "checkpoints": [
            {
                "checkpoint_id": cp.checkpoint_id,
                "project_id": cp.project_id,
                "last_event_id": cp.last_event_id,
                "records_processed": cp.records_processed,
                "status": cp.status,
                "updated_at": cp.updated_at,
            }
            for cp in checkpoints
        ],
    }


@router.post("/api/v1/operator/fault-inject", tags=["Operations"])
def trigger_fault(
    fault_type: str = Query(default="github_rate_limit_exhausted"),
    db: Session = Depends(get_db),
    _: str = Depends(_require_operator),
):
    ensure_seeded_and_trained(db)
    return inject_fault(db, fault_type=fault_type)


@router.post("/api/v1/operator/recover", response_model=RecoveryResponse, tags=["Operations"])
def trigger_recovery(
    db: Session = Depends(get_db),
    _: str = Depends(_require_operator),
):
    return recover_from_checkpoints(db)


@router.post("/api/v1/security/negative-tests/run", response_model=NegativeTestCampaignResponse, tags=["Assurance"])
def execute_negative_tests(db: Session = Depends(get_db)):
    return run_negative_test_campaign(db)


@router.get("/api/v1/audit", response_model=list[AuditEventItem], tags=["Assurance"])
def list_audit_events(limit: int = Query(default=40, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(limit)).all()
    return rows


@router.get("/api/v1/manifest", tags=["Assurance"])
def list_evidence_manifest(db: Session = Depends(get_db)):
    rows = db.scalars(select(EvidenceManifest).order_by(EvidenceManifest.partition, EvidenceManifest.manifest_id)).all()
    return [
        {
            "manifest_id": m.manifest_id,
            "source_url": m.source_url,
            "access_date": m.access_date,
            "licence": m.licence,
            "custodian": m.custodian,
            "records_info": m.records_info,
            "partition": m.partition,
            "objective_or_kpi": m.objective_or_kpi,
            "config_version": m.config_version,
        }
        for m in rows
    ]
