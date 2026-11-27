"""
Deterministic cloud-infrastructure project fixtures partitioned into:
  - 'dev': 10 labelled projects for training O4 (5 active, 5 stalled)
  - 'acceptance': 8 held-out labelled projects reserved before tuning (AC-3, 4 active, 4 stalled)
Zero repository overlap between dev and acceptance partitions (Section 3.5).
Includes high-star single-maintainer NT-1 / NT-2 trap fixtures and bot-account noise.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone


CUTOFF_DT = datetime(2025, 11, 1, 0, 0, 0, tzinfo=timezone.utc)


def _generate_project_fixture(
    repository: str,
    licence: str,
    partition: str,
    ground_truth_label: str,
    reported_stars: int,
    reported_forks: int,
    maintainer_weights: list[float],
    commits_per_month_start: int,
    commits_per_month_end: int,
    release_days_interval: int,
    release_jitter_days: int,
    last_release_gap_days: int,
    retention_ratio: float,
    median_issue_response_h: float,
    median_pr_merge_h: float,
    seed: int,
) -> dict:
    rng = random.Random(seed)
    owner = repository.split("/")[0]
    slug = repository.replace("/", "_")

    prev_maintainers = [f"{owner}-prev-{i}" for i in range(max(2, len(maintainer_weights)))]
    curr_maintainers = [f"{owner}-core-{i}" for i in range(len(maintainer_weights))]

    # Retain overlap with prev_maintainers according to retention_ratio
    retain_count = round(len(prev_maintainers) * retention_ratio)
    for i in range(min(retain_count, len(curr_maintainers))):
        curr_maintainers[i] = prev_maintainers[i]

    commits = []
    # Previous year (-24m to -12m): establish prior contributor pool
    for m in range(12):
        month_base = CUTOFF_DT - timedelta(days=720 - m * 30)
        for idx, author in enumerate(prev_maintainers):
            for k in range(3):
                ts = month_base + timedelta(days=rng.randint(0, 27), hours=rng.randint(1, 22))
                commits.append(
                    {
                        "event_id": f"{slug}:prev:{m}:{idx}:{k}",
                        "contributor_login": author,
                        "contributor_email": f"{author}@cloud-infra.org",
                        "committed_at": ts.isoformat(),
                    }
                )

    # Observation year (-12m to cutoff)
    for m in range(12):
        month_base = CUTOFF_DT - timedelta(days=360 - m * 30)
        frac = m / 11.0
        n_commits = max(1, round(commits_per_month_start + frac * (commits_per_month_end - commits_per_month_start)))
        # Add realistic maintainer drop-off when commits_per_month_end is low
        active_pool = curr_maintainers if n_commits >= 4 else curr_maintainers[:1]
        weights = maintainer_weights[: len(active_pool)]
        for k in range(n_commits):
            author = rng.choices(active_pool, weights=weights, k=1)[0]
            ts = month_base + timedelta(days=rng.randint(0, 28), hours=rng.randint(1, 22))
            commits.append(
                {
                    "event_id": f"{slug}:curr:{m}:{k}",
                    "contributor_login": author,
                    "contributor_email": f"{author}@cloud-infra.org",
                    "committed_at": ts.isoformat(),
                }
            )
        # Inject automated bot commits that must be filtered out by identity pipeline
        commits.append(
            {
                "event_id": f"{slug}:bot:{m}",
                "contributor_login": "dependabot[bot]",
                "contributor_email": "49699333+dependabot[bot]@users.noreply.github.com",
                "committed_at": (month_base + timedelta(days=14)).isoformat(),
            }
        )

    # Releases inside -12m window
    releases = []
    cursor = CUTOFF_DT - timedelta(days=last_release_gap_days)
    idx = 0
    while cursor >= CUTOFF_DT - timedelta(days=355):
        releases.append(
            {
                "release_id": f"{slug}:rel:{idx}",
                "tag": f"v1.{12 - idx}.0",
                "published_at": cursor.isoformat(),
            }
        )
        step = max(10, release_days_interval + rng.randint(-release_jitter_days, release_jitter_days))
        cursor -= timedelta(days=step)
        idx += 1

    # Issues inside -12m window
    issues = []
    for i in range(16):
        opened = CUTOFF_DT - timedelta(days=rng.randint(15, 345))
        resp_h = max(1.0, median_issue_response_h * rng.uniform(0.65, 1.45))
        resp = opened + timedelta(hours=resp_h)
        if resp > CUTOFF_DT:
            resp = None
        issues.append(
            {
                "event_id": f"{slug}:issue:{i}",
                "opened_at": opened.isoformat(),
                "first_response_at": resp.isoformat() if resp else None,
                "closed_at": (opened + timedelta(hours=resp_h * 2.5)).isoformat()
                if resp and (opened + timedelta(hours=resp_h * 2.5)) <= CUTOFF_DT
                else None,
            }
        )

    # Pull requests inside -12m window
    prs = []
    for i in range(18):
        opened = CUTOFF_DT - timedelta(days=rng.randint(12, 345))
        merge_h = max(1.0, median_pr_merge_h * rng.uniform(0.6, 1.5))
        merged = opened + timedelta(hours=merge_h)
        author = rng.choices(curr_maintainers, weights=maintainer_weights, k=1)[0]
        prs.append(
            {
                "event_id": f"{slug}:pr:{i}",
                "contributor_login": author,
                "contributor_email": f"{author}@cloud-infra.org",
                "opened_at": opened.isoformat(),
                "merged_at": merged.isoformat() if merged <= CUTOFF_DT else None,
                "closed_at": merged.isoformat() if merged <= CUTOFF_DT else None,
            }
        )

    return {
        "repository": repository,
        "owner": owner,
        "ecosystem": "cloud-infrastructure",
        "licence": licence,
        "source_version": "fixture-v1.0.0",
        "partition": partition,
        "ground_truth_label": ground_truth_label,
        "reported_stars": reported_stars,
        "reported_forks": reported_forks,
        "commits": commits,
        "releases": releases,
        "issues": issues,
        "prs": prs,
    }


def build_seed_dataset() -> list[dict]:
    """Return 10 dev-partition + 8 held-out acceptance-partition cloud-infrastructure projects."""
    specs = [
        # --- DEV PARTITION (used for training O4) ---
        ("cncf-mesh/envoy-gateway-lite", "Apache-2.0", "dev", "active", 8400, 1120, [0.22, 0.20, 0.18, 0.16, 0.14, 0.10], 18, 22, 30, 5, 18, 0.85, 14.0, 22.0, 101),
        ("kube-storage/csi-snapshotter-x", "Apache-2.0", "dev", "active", 4200, 540, [0.25, 0.22, 0.20, 0.18, 0.15], 14, 17, 38, 6, 20, 0.80, 18.0, 28.0, 102),
        ("observability/otel-ebpf-agent", "Apache-2.0", "dev", "active", 6900, 810, [0.20, 0.20, 0.18, 0.16, 0.14, 0.12], 20, 24, 28, 4, 12, 0.90, 10.0, 16.0, 103),
        ("cloud-net/cilium-policy-lint", "Apache-2.0", "dev", "active", 1950, 240, [0.28, 0.24, 0.20, 0.16, 0.12], 10, 13, 45, 7, 24, 0.78, 24.0, 36.0, 104),
        ("serverless-ops/knative-autoscaler-pro", "MIT", "dev", "active", 3100, 410, [0.26, 0.22, 0.20, 0.18, 0.14], 12, 14, 40, 8, 22, 0.75, 22.0, 32.0, 105),
        # Dev Stalled projects (including high-star single-maintainer trap!)
        ("star-trap/kube-zero-trust-proxy", "MIT", "dev", "stalled", 28500, 3100, [0.92, 0.05, 0.03], 14, 3, 35, 6, 40, 0.20, 210.0, 280.0, 106),
        ("legacy-cloud/docker-swarm-bridge", "Apache-2.0", "dev", "stalled", 9200, 1400, [0.85, 0.10, 0.05], 10, 2, 110, 35, 195, 0.15, 310.0, 420.0, 107),
        ("edge-infra/microvm-orchestrator", "BSD-3-Clause", "dev", "stalled", 11400, 980, [0.88, 0.08, 0.04], 12, 2, 95, 30, 170, 0.22, 260.0, 340.0, 108),
        ("kube-tools/helm-drift-scanner", "MIT", "dev", "stalled", 5400, 620, [0.76, 0.15, 0.09], 8, 2, 120, 40, 210, 0.25, 290.0, 360.0, 109),
        ("cloud-sec/vault-auto-unseal-lite", "MPL-2.0", "dev", "stalled", 14200, 1250, [0.90, 0.07, 0.03], 9, 2, 42, 10, 90, 0.18, 240.0, 310.0, 110),
        # --- HELD-OUT ACCEPTANCE PARTITION (AC-3: never used in training/tuning) ---
        ("cncf-runtime/containerd-shim-wasm", "Apache-2.0", "acceptance", "active", 7600, 890, [0.24, 0.21, 0.19, 0.18, 0.18], 16, 20, 32, 5, 15, 0.85, 15.0, 20.0, 201),
        ("cloud-dns/coredns-mesh-sync", "Apache-2.0", "acceptance", "active", 2300, 310, [0.27, 0.23, 0.20, 0.16, 0.14], 11, 14, 42, 6, 19, 0.80, 20.0, 28.0, 202),
        ("infra-gitops/flux-drift-reconciler", "Apache-2.0", "acceptance", "active", 5200, 610, [0.23, 0.21, 0.20, 0.19, 0.17], 15, 18, 35, 5, 14, 0.82, 16.0, 24.0, 203),
        ("k8s-sched/volcano-gpu-broker", "Apache-2.0", "acceptance", "active", 3800, 470, [0.25, 0.22, 0.20, 0.18, 0.15], 12, 15, 40, 7, 21, 0.78, 22.0, 30.0, 204),
        # Held-out Stalled projects (including NT-1 popular single-maintainer project!)
        ("hype-cloud/k8s-ai-pod-scaler", "MIT", "acceptance", "stalled", 34200, 3900, [0.94, 0.04, 0.02], 12, 2, 32, 5, 35, 0.15, 250.0, 330.0, 205),
        ("solo-ops/terraform-state-guardian", "MPL-2.0", "acceptance", "stalled", 16800, 1750, [0.89, 0.07, 0.04], 11, 2, 45, 8, 60, 0.20, 230.0, 300.0, 206),
        ("mesh-archive/istio-canary-wizard", "Apache-2.0", "acceptance", "stalled", 7900, 820, [0.78, 0.14, 0.08], 9, 2, 115, 35, 185, 0.22, 280.0, 350.0, 207),
        ("cluster-bak/etcd-snapshot-daemon", "MIT", "acceptance", "stalled", 11200, 990, [0.84, 0.11, 0.05], 10, 2, 90, 28, 165, 0.18, 270.0, 380.0, 208),
    ]
    return [_generate_project_fixture(*spec) for spec in specs]
