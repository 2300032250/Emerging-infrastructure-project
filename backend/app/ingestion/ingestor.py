"""Idempotent batched ingestion with durable checkpoints and replay recovery (Section 4.7)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.identity import is_bot_account, normalize_identity
from app.ingestion.validator import validate_repository_payload
from app.models import (
    AuditEvent,
    Checkpoint,
    CommitEvent,
    Contributor,
    EvidenceManifest,
    IssueEvent,
    Project,
    PullRequestEvent,
    ReleaseEvent,
)


def _to_dt(val: datetime | str | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val.astimezone(timezone.utc)
    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def ingest_project_payload(db: Session, payload: dict, partition: str = "live") -> dict:
    """
    Validate and idempotently ingest a repository activity payload with durable checkpointing.

    Safe to replay after a partial failure: existing event_ids are skipped without duplication.
    """
    validate_repository_payload(payload)

    repository = payload["repository"]
    project_id = repository.replace("/", "__").lower()
    owner = payload.get("owner") or repository.split("/")[0]
    source_version = payload["source_version"]

    project = db.get(Project, project_id)
    if project is None:
        project = Project(
            project_id=project_id,
            repository=repository,
            owner=owner,
            ecosystem=payload.get("ecosystem", "cloud-infrastructure"),
            licence=payload["licence"],
            source_version=source_version,
            partition=partition,
            reported_stars=int(payload.get("reported_stars", 0)),
            reported_forks=int(payload.get("reported_forks", 0)),
            ground_truth_label=payload.get("ground_truth_label"),
        )
        db.add(project)
    else:
        project.source_version = source_version
        project.licence = payload["licence"]
        project.reported_stars = int(payload.get("reported_stars", project.reported_stars))
        project.reported_forks = int(payload.get("reported_forks", project.reported_forks))
        if payload.get("ground_truth_label") is not None:
            project.ground_truth_label = payload["ground_truth_label"]

    bots_filtered = 0
    aliases_resolved = 0
    seen_contributors: dict[str, Contributor] = {}

    def resolve_contributor(login: str, email: str = "") -> str:
        nonlocal bots_filtered, aliases_resolved
        cid = normalize_identity(login, email)
        bot_flag = is_bot_account(login, email)
        existing = seen_contributors.get(cid) or db.get(Contributor, cid)
        if existing is None:
            existing = Contributor(contributor_id=cid, is_bot=bot_flag, aliases=[login])
            db.add(existing)
            seen_contributors[cid] = existing
            if bot_flag:
                bots_filtered += 1
        else:
            seen_contributors[cid] = existing
            if login not in existing.aliases:
                existing.aliases = [*existing.aliases, login]
                aliases_resolved += 1
        return cid

    commits_added = 0
    last_event_id = "none"
    for c in payload.get("commits", []):
        eid = c["event_id"]
        last_event_id = eid
        if db.get(CommitEvent, eid) is None:
            cid = resolve_contributor(c["contributor_login"], c.get("contributor_email", ""))
            db.add(
                CommitEvent(
                    event_id=eid,
                    project_id=project_id,
                    contributor_id=cid,
                    committed_at=_to_dt(c["committed_at"]),
                )
            )
            commits_added += 1

    releases_added = 0
    for r in payload.get("releases", []):
        rid = r["release_id"]
        last_event_id = rid
        if db.get(ReleaseEvent, rid) is None:
            db.add(
                ReleaseEvent(
                    release_id=rid,
                    project_id=project_id,
                    tag=r["tag"],
                    published_at=_to_dt(r["published_at"]),
                )
            )
            releases_added += 1

    issues_added = 0
    for iss in payload.get("issues", []):
        eid = iss["event_id"]
        last_event_id = eid
        if db.get(IssueEvent, eid) is None:
            db.add(
                IssueEvent(
                    event_id=eid,
                    project_id=project_id,
                    opened_at=_to_dt(iss["opened_at"]),
                    first_response_at=_to_dt(iss.get("first_response_at")),
                    closed_at=_to_dt(iss.get("closed_at")),
                )
            )
            issues_added += 1

    prs_added = 0
    for pr in payload.get("prs", []):
        eid = pr["event_id"]
        last_event_id = eid
        if db.get(PullRequestEvent, eid) is None:
            cid = resolve_contributor(pr["contributor_login"], pr.get("contributor_email", ""))
            db.add(
                PullRequestEvent(
                    event_id=eid,
                    project_id=project_id,
                    contributor_id=cid,
                    opened_at=_to_dt(pr["opened_at"]),
                    closed_at=_to_dt(pr.get("closed_at")),
                    merged_at=_to_dt(pr.get("merged_at")),
                )
            )
            prs_added += 1

    total_added = commits_added + releases_added + issues_added + prs_added
    cp_id = f"cp:{project_id}"
    checkpoint = db.get(Checkpoint, cp_id)
    if checkpoint is None:
        checkpoint = Checkpoint(
            checkpoint_id=cp_id,
            source_name=payload.get("source_name", "github-rest-or-fixture"),
            project_id=project_id,
            last_event_id=last_event_id,
            records_processed=total_added,
            status="ok",
        )
        db.add(checkpoint)
    else:
        checkpoint.last_event_id = last_event_id
        checkpoint.records_processed += total_added
        checkpoint.status = "ok"
        checkpoint.updated_at = datetime.now(timezone.utc)

    manifest_id = f"manifest:{project_id}:{source_version}"
    if db.get(EvidenceManifest, manifest_id) is None:
        db.add(
            EvidenceManifest(
                manifest_id=manifest_id[:64],
                source_url=f"https://github.com/{repository}",
                licence=payload["licence"],
                custodian=owner,
                records_info=(
                    f"commits={len(payload.get('commits', []))}, "
                    f"releases={len(payload.get('releases', []))}, "
                    f"issues={len(payload.get('issues', []))}, "
                    f"prs={len(payload.get('prs', []))}"
                ),
                partition=partition,
                objective_or_kpi="O2,O3,O4" if partition != "acceptance" else "O5,AC-1,AC-3",
                config_version=settings.config_version,
            )
        )

    db.add(
        AuditEvent(
            audit_id=f"aud-{uuid.uuid4().hex[:12]}",
            event_type="INGESTION_COMPLETED",
            actor_role="operator",
            project_id=project_id,
            config_hash=settings.config_hash,
            detail=f"Ingested {repository} (version={source_version}, partition={partition}).",
            metadata_json={
                "commits_added": commits_added,
                "releases_added": releases_added,
                "issues_added": issues_added,
                "prs_added": prs_added,
                "bots_filtered": bots_filtered,
                "aliases_resolved": aliases_resolved,
            },
        )
    )
    db.commit()

    return {
        "project_id": project_id,
        "repository": repository,
        "source_version": source_version,
        "commits_ingested": commits_added,
        "releases_ingested": releases_added,
        "issues_ingested": issues_added,
        "prs_ingested": prs_added,
        "bots_filtered": bots_filtered,
        "aliases_resolved": aliases_resolved,
        "checkpoint_id": cp_id,
    }
