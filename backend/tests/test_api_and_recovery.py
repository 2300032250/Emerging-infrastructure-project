"""Integration tests for FastAPI contracts, role separation, degraded mode, and checkpoint recovery."""


def test_health_and_evaluation_metrics(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    h = health.json()
    assert h["status"] == "healthy"
    assert h["model_trained"] is True
    assert h["total_projects"] == 18

    eval_resp = client.get("/api/v1/evaluation/summary", params={"trials": 30})
    assert eval_resp.status_code == 200
    ev = eval_resp.json()
    assert ev["partition"] == "acceptance"
    assert ev["sample_size"] == 8
    kpi_map = {k["kpi_id"]: k for k in ev["kpis"]}
    assert kpi_map["KPI-1"]["achieved"] >= 75.0
    assert kpi_map["KPI-6"]["passed"] is True


def test_operator_role_separation_and_fault_recovery(client):
    # Decision maker cannot invoke operator endpoints (Section 4.6)
    forbidden = client.get("/api/v1/operator/status", headers={"X-Actor-Role": "decision_maker"})
    assert forbidden.status_code == 403

    # Trigger assessment first so a valid snapshot exists
    pid = "cncf-runtime__containerd-shim-wasm"
    fresh = client.post("/api/v1/assessments/run", json={"project_id": pid})
    assert fresh.status_code == 200
    assert fresh.json()["is_stale"] is False

    # Inject fault -> enters degraded mode
    fault = client.post(
        "/api/v1/operator/fault-inject",
        params={"fault_type": "github_rate_limit_exhausted"},
        headers={"X-Actor-Role": "operator"},
    )
    assert fault.status_code == 200
    assert fault.json()["degraded_mode"] is True

    # Assessment request during degraded mode returns last valid snapshot explicitly marked stale
    degraded = client.post("/api/v1/assessments/run", json={"project_id": pid})
    assert degraded.status_code == 200
    assert degraded.json()["is_stale"] is True
    assert "Degraded mode active" in degraded.json()["stale_reason"]

    # Recover via checkpoint replay
    rec = client.post("/api/v1/operator/recover", headers={"X-Actor-Role": "operator"})
    assert rec.status_code == 200
    assert rec.json()["recovered"] is True
    assert rec.json()["degraded_mode"] is False


def test_synthetic_ingestion_and_prometheus_metrics(client):
    ing = client.post(
        "/api/v1/projects/ingest",
        json={"repository": "custom-org/kube-ebpf-router", "mode": "synthetic_fixture", "licence": "Apache-2.0"},
    )
    assert ing.status_code == 200
    assert ing.json()["project_id"] == "custom-org__kube-ebpf-router"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "maturity_assessments_total" in metrics.text
