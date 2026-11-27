"""Schema, provenance, and range validation gates for untrusted repository data (FR-1, Section 4.6, 6.3)."""

from __future__ import annotations

import re
from datetime import datetime, timezone


class ValidationGateError(ValueError):
    """Raised when incoming repository data fails schema, provenance, or range checks."""


REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def validate_repository_payload(payload: dict) -> None:
    """Validate provenance, licence, version, and temporal consistency before ingestion."""
    repo = payload.get("repository", "")
    if not REPO_PATTERN.match(repo):
        raise ValidationGateError(f"Invalid repository identifier '{repo}'; expected 'owner/repo'.")

    if not payload.get("source_version"):
        raise ValidationGateError("Missing required provenance field 'source_version' (NT-4).")

    if not payload.get("licence"):
        raise ValidationGateError("Missing required licence metadata for repository evidence manifest.")

    now = datetime.now(timezone.utc)

    for c in payload.get("commits", []):
        if not c.get("event_id") or not c.get("contributor_login") or not c.get("committed_at"):
            raise ValidationGateError("Commit event missing required event_id, contributor_login, or committed_at.")
        ts = _to_utc(c["committed_at"])
        if ts > now:
            raise ValidationGateError(f"Commit timestamp {ts.isoformat()} is in the future.")

    for r in payload.get("releases", []):
        if not r.get("release_id") or not r.get("tag") or not r.get("published_at"):
            raise ValidationGateError("Release event missing required release_id, tag, or published_at.")
        ts = _to_utc(r["published_at"])
        if ts > now:
            raise ValidationGateError(f"Release timestamp {ts.isoformat()} is in the future.")

    for iss in payload.get("issues", []):
        opened = _to_utc(iss["opened_at"])
        resp = iss.get("first_response_at")
        closed = iss.get("closed_at")
        if resp is not None and _to_utc(resp) < opened:
            raise ValidationGateError("Issue first_response_at precedes opened_at.")
        if closed is not None and _to_utc(closed) < opened:
            raise ValidationGateError("Issue closed_at precedes opened_at.")

    for pr in payload.get("prs", []):
        opened = _to_utc(pr["opened_at"])
        merged = pr.get("merged_at")
        closed = pr.get("closed_at")
        if merged is not None and _to_utc(merged) < opened:
            raise ValidationGateError("Pull request merged_at precedes opened_at.")
        if closed is not None and _to_utc(closed) < opened:
            raise ValidationGateError("Pull request closed_at precedes opened_at.")


def _to_utc(val: datetime | str) -> datetime:
    if isinstance(val, str):
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
    else:
        dt = val
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
