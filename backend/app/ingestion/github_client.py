"""GitHub REST API client with timeout, backoff, rate-limit pause, and fail-closed auth (Section 4.7, NT-5)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings


class GitHubAuthError(PermissionError):
    """Raised when GitHub API returns 401/403 due to invalid or expired token (NT-5)."""


class GitHubRateLimitPaused(RuntimeError):
    """Raised when GitHub API rate limit is exhausted so ingestion pauses safely at checkpoint."""


class GitHubAPIClient:
    """Fetches public repository commits, releases, issues, and PRs from GitHub REST API v3."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None, timeout: float = settings.github_timeout_seconds) -> None:
        self.token = token if token is not None else settings.github_token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "CLOUD-225-Maturity-Assessor/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, client: httpx.Client, path: str, params: dict | None = None) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = client.get(f"{self.BASE_URL}{path}", headers=self._headers(), params=params)
                if resp.status_code == 401:
                    raise GitHubAuthError("NT-5: GitHub API authentication failed (invalid or expired token).")
                if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                    raise GitHubRateLimitPaused("GitHub API rate limit reached; pausing at durable checkpoint.")
                if resp.status_code in (429, 502, 503):
                    time.sleep(0.5 * (2**attempt))
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"GitHub API request failed after retries: {last_exc}")

    def fetch_repository_activity(self, repository: str) -> dict:
        """Fetch metadata, recent commits, releases, issues, and PRs for owner/repo."""
        since = (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()
        with httpx.Client(timeout=self.timeout) as client:
            repo_meta = self._get(client, f"/repos/{repository}").json()
            commits_raw = self._get(
                client, f"/repos/{repository}/commits", params={"since": since, "per_page": 100}
            ).json()
            releases_raw = self._get(
                client, f"/repos/{repository}/releases", params={"per_page": 50}
            ).json()
            issues_raw = self._get(
                client, f"/repos/{repository}/issues", params={"state": "all", "since": since, "per_page": 60}
            ).json()
            prs_raw = self._get(
                client, f"/repos/{repository}/pulls", params={"state": "all", "per_page": 60}
            ).json()

        licence_info = (repo_meta.get("license") or {}).get("spdx_id") or "NOASSERTION"
        commits = []
        for idx, c in enumerate(commits_raw):
            author_obj = c.get("author") or {}
            commit_author = (c.get("commit") or {}).get("author") or {}
            login = author_obj.get("login") or commit_author.get("name") or f"anon-{idx}"
            commits.append(
                {
                    "event_id": f"{repository}:commit:{c.get('sha', idx)}",
                    "contributor_login": login,
                    "contributor_email": commit_author.get("email", ""),
                    "committed_at": commit_author.get("date"),
                }
            )

        releases = [
            {
                "release_id": f"{repository}:release:{r.get('id')}",
                "tag": r.get("tag_name", "unknown"),
                "published_at": r.get("published_at") or r.get("created_at"),
            }
            for r in releases_raw
            if r.get("published_at") or r.get("created_at")
        ]

        issues = [
            {
                "event_id": f"{repository}:issue:{i.get('number')}",
                "opened_at": i.get("created_at"),
                "first_response_at": i.get("updated_at") if i.get("comments", 0) > 0 else None,
                "closed_at": i.get("closed_at"),
            }
            for i in issues_raw
            if "pull_request" not in i
        ]

        prs = [
            {
                "event_id": f"{repository}:pr:{p.get('number')}",
                "contributor_login": (p.get("user") or {}).get("login") or "unknown",
                "contributor_email": "",
                "opened_at": p.get("created_at"),
                "closed_at": p.get("closed_at"),
                "merged_at": p.get("merged_at"),
            }
            for p in prs_raw
        ]

        return {
            "repository": repository,
            "owner": (repo_meta.get("owner") or {}).get("login") or repository.split("/")[0],
            "licence": licence_info,
            "source_version": f"github-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            "reported_stars": int(repo_meta.get("stargazers_count", 0)),
            "reported_forks": int(repo_meta.get("forks_count", 0)),
            "commits": commits,
            "releases": releases,
            "issues": issues,
            "prs": prs,
        }
