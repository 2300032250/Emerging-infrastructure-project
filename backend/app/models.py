"""ORM models implementing Table 4 (Data Model) and append-only audit guarantees (NT-4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImmutableRecordError(ValueError):
    """Raised when attempting to mutate or delete an append-only audit or assessment record (NT-4)."""


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    repository: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    owner: Mapped[str] = mapped_column(String(128))
    ecosystem: Mapped[str] = mapped_column(String(64), default="cloud-infrastructure")
    licence: Mapped[str] = mapped_column(String(64))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_version: Mapped[str] = mapped_column(String(64))
    partition: Mapped[str] = mapped_column(String(32), default="dev")  # 'dev' | 'acceptance' | 'live'
    # Popularity metadata stored purely for NT-1 / NT-3 demonstration and audit; NEVER used as model features.
    reported_stars: Mapped[int] = mapped_column(Integer, default=0)
    reported_forks: Mapped[int] = mapped_column(Integer, default=0)
    # Ground-truth label for evaluation partitions ('stalled' | 'active' | None)
    ground_truth_label: Mapped[str | None] = mapped_column(String(32), nullable=True)

    assessments: Mapped[list["Assessment"]] = relationship(back_populates="project")


class Contributor(Base):
    __tablename__ = "contributors"

    contributor_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)


class CommitEvent(Base):
    __tablename__ = "commit_events"

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    contributor_id: Mapped[str] = mapped_column(ForeignKey("contributors.contributor_id"), index=True)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ReleaseEvent(Base):
    __tablename__ = "release_events"

    release_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    tag: Mapped[str] = mapped_column(String(128))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class IssueEvent(Base):
    __tablename__ = "issue_events"

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PullRequestEvent(Base):
    __tablename__ = "pull_request_events"

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    contributor_id: Mapped[str] = mapped_column(ForeignKey("contributors.contributor_id"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Assessment(Base):
    """Append-only assessment table (Table 4 & NT-4)."""

    __tablename__ = "assessments"

    assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    input_version: Mapped[str] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))
    indicators: Mapped[dict[str, Any]] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    project: Mapped["Project"] = relationship(back_populates="assessments")


class Checkpoint(Base):
    """Durable checkpoint per ingested source/project for idempotent replay (Section 4.7)."""

    __tablename__ = "checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    last_event_id: Mapped[str] = mapped_column(String(160))
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="ok")  # 'ok' | 'paused_rate_limit' | 'faulted'
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    """Immutable append-only audit log for security, NT, and operator events (NT-4, NT-5)."""

    __tablename__ = "audit_events"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor_role: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_hash: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class EvidenceManifest(Base):
    """Evidence manifest tracking provenance and partition isolation (Table 3 & Appendix B)."""

    __tablename__ = "evidence_manifest"

    manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(512))
    access_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    licence: Mapped[str] = mapped_column(String(128))
    custodian: Mapped[str] = mapped_column(String(128))
    records_info: Mapped[str] = mapped_column(Text)
    partition: Mapped[str] = mapped_column(String(32))
    objective_or_kpi: Mapped[str] = mapped_column(String(128))
    config_version: Mapped[str] = mapped_column(String(64))


def _block_mutation(mapper, connection, target) -> None:
    raise ImmutableRecordError(
        f"NT-4 security policy: {target.__class__.__name__} is append-only and cannot be modified or deleted."
    )


for _immutable_cls in (Assessment, AuditEvent):
    event.listen(_immutable_cls, "before_update", _block_mutation)
    event.listen(_immutable_cls, "before_delete", _block_mutation)
