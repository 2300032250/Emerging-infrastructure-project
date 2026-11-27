"""Mandatory Negative-Test Campaign NT-1 to NT-5 (Table 6, Section 6.2)."""

from app.models import AuditEvent


def test_negative_test_campaign_nt1_to_nt5_all_pass(client):
    resp = client.post("/api/v1/security/negative-tests/run")
    assert resp.status_code == 200
    data = resp.json()
    assert data["all_passed"] is True
    assert len(data["results"]) == 5
    for result in data["results"]:
        assert result["passed"] is True, f"{result['test_id']} failed: {result['observed_behaviour']}"
        assert result["audit_event_id"].startswith("aud-")


def test_nt3_popularity_sort_overridden_and_audited(client):
    resp = client.get("/api/v1/projects", params={"sort_by": "stars", "partition": "acceptance"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["popularity_sort_overridden"] is True
    assert body["sort_applied"] == "sustainability_desc"
    assert "NT-3 Guard" in body["audit_notice"]

    audit_resp = client.get("/api/v1/audit")
    assert audit_resp.status_code == 200
    events = [e["event_type"] for e in audit_resp.json()]
    assert "POPULARITY_SORT_OVERRIDDEN" in events
