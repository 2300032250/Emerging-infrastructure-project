"""Contributor identity resolution and bot account filtering (Section 5.3 & 9.3)."""

from __future__ import annotations

import re


BOT_PATTERNS = (
    "[bot]",
    "dependabot",
    "renovate",
    "github-actions",
    "codecov",
    "snyk-bot",
    "greenkeeper",
    "mergify",
    "release-please",
)


def is_bot_account(login: str, email: str = "") -> bool:
    combined = f"{login} {email}".lower()
    return any(pattern in combined for pattern in BOT_PATTERNS)


def normalize_identity(login: str, email: str = "") -> str:
    """Resolve email/name aliases into a canonical contributor identifier."""
    clean_login = re.sub(r"[^a-z0-9_-]", "", login.strip().lower())
    if email and "@" in email and not email.endswith("users.noreply.github.com"):
        local, domain = email.strip().lower().split("@", 1)
        clean_local = re.sub(r"\+.*$", "", local)
        return f"person:{clean_local}@{domain}"
    return f"gh:{clean_login or 'unknown'}"
