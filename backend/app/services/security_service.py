"""Mandatory Negative-Test Campaign NT-1 to NT-5 (Table 6, FR-7, Section 6.2 & 6.3)."""

from __future__ import annotations

import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.analytics.indicators import PopularityGuardError, assert_no_popularity_features
from app.config import ConfigurationError, Settings, settings, validate_startup_config
from app.ingestion.github_client import GitHubAPIClient, GitHubAuthError
from app.ingestion.validator import ValidationGateError, validate_repository_payload
from app.models import Assessment, AuditEvent, ImmutableRecordError, Project
from app.services.assessment_service import ensure_seeded_and_trained, run_assessment
from app.services.telemetry import runtime_state


def run_negative_test_campaign(db: Session) -> dict:
    """Execute NT-1 through NT-5 live against controlled fixtures and record immutable audit evidence."""
    ensure_seeded_and_trained(db)
    results = []

    # NT-1: Stars and cadence read as maturity
    t0 = time.perf_counter()
    nt1_passed = False
    nt1_obs = ""
    try:
        try:
            assert_no_popularity_features(["top_contributor_share", "reported_stars", "release_count_12m"])
        except PopularityGuardError:
            nt1_guard_ok = True
        else:
            nt1_guard_ok = False

        trap_proj = db.get(Project, "hype-cloud__k8s-ai-pod-scaler")
        res = run_assessment(db, trap_proj.project_id, actor_role="security_harness")
        nt1_passed = (
            nt1_guard_ok
            and res["risk_level"] == "CRITICAL_SINGLE_MAINTAINER"
            and res["continuity_score"] <= 0.39
            and res["popularity_trap_warning"] is not None
        )
        nt1_obs = (
            f"Popularity guard rejected stars; project ({trap_proj.reported_stars:,} stars) "
            f"scored {res['continuity_percent']}% ({res['risk_level']})."
        )
    except Exception as exc:
        nt1_obs = f"NT-1 failed: {exc}"
    aud1 = _record_nt_audit(db, "NT-1", nt1_passed, nt1_obs)
    results.append(
        {
            "test_id": "NT-1",
            "name": "Stars and cadence read as maturity",
            "condition": "High-star (34.2k) regular-release project with 1 dominant maintainer",
            "fixture_id": "hype-cloud__k8s-ai-pod-scaler",
            "passed": nt1_passed,
            "expected_behaviour": "Popularity guard blocks stars; single-maintainer risk caps continuity <= 39%.",
            "observed_behaviour": nt1_obs,
            "recovery_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "residual_risk": "Low — structural guard enforced in feature extractor and predictor.",
            "audit_event_id": aud1,
        }
    )

    # NT-2: Single-maintainer component in an enterprise platform
    t0 = time.perf_counter()
    nt2_passed = False
    nt2_obs = ""
    try:
        res2 = run_assessment(db, "solo-ops__terraform-state-guardian", actor_role="security_harness")
        nt2_passed = (
            res2["risk_level"] == "CRITICAL_SINGLE_MAINTAINER"
            and len(res2["top_contributors"]) == 3
            and "single maintainer" in res2["plain_language_explanation"].lower()
        )
        nt2_obs = f"Flagged {res2['risk_level']} with 3 contributing indicators and plain-language explanation."
    except Exception as exc:
        nt2_obs = f"NT-2 failed: {exc}"
    aud2 = _record_nt_audit(db, "NT-2", nt2_passed, nt2_obs)
    results.append(
        {
            "test_id": "NT-2",
            "name": "Single-maintainer component in enterprise platform",
            "condition": "Enterprise platform dependency with single-maintainer concentration",
            "fixture_id": "solo-ops__terraform-state-guardian",
            "passed": nt2_passed,
            "expected_behaviour": "Component flagged with top 3 contributing indicators and explanation.",
            "observed_behaviour": nt2_obs,
            "recovery_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "residual_risk": "Low — public commit email aliases may occasionally over- or under-count.",
            "audit_event_id": aud2,
        }
    )

    # NT-3: Popularity driving adoption (ranking request sorted by popularity)
    t0 = time.perf_counter()
    from app.api.routes import list_projects_with_sustainability_guard

    listing = list_projects_with_sustainability_guard(db=db, sort_by="stars", partition="acceptance")
    nt3_passed = listing["popularity_sort_overridden"] is True and listing["sort_applied"] == "sustainability_desc"
    nt3_obs = (
        f"Requested sort_by='stars'; service enforced sort='{listing['sort_applied']}' "
        f"and emitted audit notice: {listing['audit_notice']}"
    )
    aud3 = _record_nt_audit(db, "NT-3", nt3_passed, nt3_obs)
    results.append(
        {
            "test_id": "NT-3",
            "name": "Popularity driving adoption",
            "condition": "Ranking request explicitly asks to sort by GitHub stars",
            "fixture_id": "sort_by=stars",
            "passed": nt3_passed,
            "expected_behaviour": "Service overrides with sustainability ranking and logs discrepancy.",
            "observed_behaviour": nt3_obs,
            "recovery_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "residual_risk": "Low — API contract rejects popularity-ordered rankings.",
            "audit_event_id": aud3,
        }
    )

    # NT-4: Audit evidence incomplete or mutable
    t0 = time.perf_counter()
    missing_version_blocked = False
    mutation_blocked = False
    try:
        validate_repository_payload({"repository": "org/missing-ver", "licence": "MIT"})
    except ValidationGateError:
        missing_version_blocked = True

    sample_asmt = db.query(Assessment).first()
    original_score = sample_asmt.score if sample_asmt else None
    if sample_asmt is not None:
        try:
            sample_asmt.score = 0.9999
            db.flush()
        except ImmutableRecordError:
            db.rollback()
            mutation_blocked = True
        finally:
            db.expire_all()

    nt4_passed = missing_version_blocked and mutation_blocked
    nt4_obs = (
        f"Missing source_version refused={missing_version_blocked}; "
        f"assessment mutation blocked={mutation_blocked} (score preserved at {original_score})."
    )
    aud4 = _record_nt_audit(db, "NT-4", nt4_passed, nt4_obs)
    results.append(
        {
            "test_id": "NT-4",
            "name": "Audit evidence incomplete or mutable",
            "condition": "Payload missing source_version + attempted UPDATE on stored Assessment",
            "fixture_id": "fixture-nt4-immutability",
            "passed": nt4_passed,
            "expected_behaviour": "Incomplete provenance refused; stored assessment stays immutable.",
            "observed_behaviour": nt4_obs,
            "recovery_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "residual_risk": "Low — DB trigger/ORM listener prevents UPDATE/DELETE on assessments and audit log.",
            "audit_event_id": aud4,
        }
    )

    # NT-5: Dependency, secret or configuration change invalidates threat model
    t0 = time.perf_counter()
    unpinned_blocked = False
    invalid_cfg_blocked = False
    expired_token_blocked = False

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("fastapi==0.115.6\nrequests>=2.0.0\n")
        tmp_req = Path(tf.name)
    try:
        validate_startup_config(settings, requirements_path=tmp_req)
    except ConfigurationError:
        unpinned_blocked = True
    finally:
        tmp_req.unlink(missing_ok=True)

    try:
        Settings(config_version="unversioned-dev")
    except ValidationError:
        invalid_cfg_blocked = True

    class _Fake401Response:
        status_code = 401
        headers = {}

    class _FakeClient:
        def get(self, *args, **kwargs):
            return _Fake401Response()

    try:
        GitHubAPIClient(token="expired_tok")._get(_FakeClient(), "/repos/org/repo")
    except GitHubAuthError:
        expired_token_blocked = True

    nt5_passed = unpinned_blocked and invalid_cfg_blocked and expired_token_blocked
    nt5_obs = (
        f"Unpinned dep denied={unpinned_blocked}, invalid config denied={invalid_cfg_blocked}, "
        f"expired token fail-closed={expired_token_blocked}."
    )
    aud5 = _record_nt_audit(db, "NT-5", nt5_passed, nt5_obs)
    results.append(
        {
            "test_id": "NT-5",
            "name": "Dependency, secret or configuration drift",
            "condition": "Unpinned dependency, unversioned config, and 401 expired GitHub token",
            "fixture_id": "fixture-nt5-config-drift",
            "passed": nt5_passed,
            "expected_behaviour": "Unsafe actions denied fail-closed; valid state kept; immutable audit emitted.",
            "observed_behaviour": nt5_obs,
            "recovery_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "residual_risk": "Low — startup validation and auth fail-closed guards verified.",
            "audit_event_id": aud5,
        }
    )

    return {
        "all_passed": all(r["passed"] for r in results),
        "executed_at": datetime.now(timezone.utc),
        "results": results,
    }


def _record_nt_audit(db: Session, test_id: str, passed: bool, detail: str) -> str:
    runtime_state.record_nt_guard()
    audit_id = f"aud-{uuid.uuid4().hex[:12]}"
    db.add(
        AuditEvent(
            audit_id=audit_id,
            event_type=f"NEGATIVE_TEST_{test_id}",
            actor_role="security_harness",
            project_id=None,
            config_hash=settings.config_hash,
            detail=f"{test_id} {'PASSED' if passed else 'FAILED'}: {detail}",
            metadata_json={"test_id": test_id, "passed": passed},
        )
    )
    db.commit()
    return audit_id
