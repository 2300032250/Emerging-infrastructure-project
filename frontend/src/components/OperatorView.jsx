import React, { useEffect, useState } from "react";
import { api } from "../api/client";

export function OperatorView({ onStatusChange }) {
  const [opStatus, setOpStatus] = useState(null);
  const [ntResults, setNtResults] = useState(null);
  const [auditEvents, setAuditEvents] = useState([]);
  const [manifest, setManifest] = useState([]);
  const [recoveryBanner, setRecoveryBanner] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function refreshAll() {
    setError("");
    try {
      const [status, audit, man] = await Promise.all([
        api.getOperatorStatus(),
        api.getAuditEvents(30),
        api.getEvidenceManifest(),
      ]);
      setOpStatus(status);
      setAuditEvents(audit || []);
      setManifest(man || []);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    refreshAll();
  }, []);

  async function handleInjectFault() {
    setLoading(true);
    setRecoveryBanner("");
    try {
      await api.injectFault("github_rate_limit_exhausted");
      await refreshAll();
      onStatusChange?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRecover() {
    setLoading(true);
    try {
      const res = await api.recoverCheckpoints();
      setRecoveryBanner(res.message);
      await refreshAll();
      onStatusChange?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRunNegativeTests() {
    setLoading(true);
    setError("");
    try {
      const res = await api.runNegativeTests();
      setNtResults(res);
      await refreshAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      {error && <div className="banner banner-danger">{error}</div>}
      {recoveryBanner && <div className="banner banner-ok">{recoveryBanner}</div>}

      {opStatus && (
        <div className="card">
          <div className="card-header-row">
            <div>
              <h2>Operator Reliability &amp; Checkpoint Recovery Console</h2>
              <p className="muted">
                Role-separated operator view (Section 4.6 &amp; 5.2). Inject faults to test stale-marked degraded mode and verify checkpoint replay.
              </p>
            </div>
            <div className="row-actions">
              <button type="button" className="btn-danger" onClick={handleInjectFault} disabled={loading}>
                Inject Fault (Degraded Mode)
              </button>
              <button type="button" className="btn-primary" onClick={handleRecover} disabled={loading}>
                Run Checkpoint Recovery
              </button>
            </div>
          </div>

          <div className="metrics-grid">
            <div className="metric-box">
              <span>Operating Mode</span>
              <strong>{opStatus.degraded_mode ? "DEGRADED (STALE)" : "NORMAL"}</strong>
            </div>
            <div className="metric-box">
              <span>Active Fault</span>
              <strong>{opStatus.active_fault || "None"}</strong>
            </div>
            <div className="metric-box">
              <span>Oldest Checkpoint Age</span>
              <strong>{opStatus.oldest_checkpoint_age_seconds ?? 0} s</strong>
            </div>
            <div className="metric-box">
              <span>Total Checkpoints</span>
              <strong>{opStatus.total_checkpoints}</strong>
            </div>
            <div className="metric-box">
              <span>Service Errors</span>
              <strong>{opStatus.error_count}</strong>
            </div>
            <div className="metric-box">
              <span>NT Guard Triggers</span>
              <strong>{opStatus.nt_guard_triggers}</strong>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header-row">
          <div>
            <h3>Mandatory Negative-Test Campaign (NT-1 to NT-5)</h3>
            <p className="muted">Exercises Table 6 conditions live against system guards and immutable audit storage.</p>
          </div>
          <button type="button" className="btn-primary" onClick={handleRunNegativeTests} disabled={loading}>
            {loading ? "Running..." : "Execute NT-1 to NT-5"}
          </button>
        </div>

        {ntResults && (
          <div className="stack-sm">
            <div className={`banner ${ntResults.all_passed ? "banner-ok" : "banner-danger"}`}>
              Campaign Result: {ntResults.all_passed ? "ALL 5 NEGATIVE TESTS PASSED" : "ONE OR MORE TESTS FAILED"}
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Condition</th>
                    <th>Observed Behaviour</th>
                    <th>Time</th>
                    <th>Audit ID</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {ntResults.results.map((r) => (
                    <tr key={r.test_id}>
                      <td><strong>{r.test_id}</strong></td>
                      <td>{r.name}</td>
                      <td className="small">{r.observed_behaviour}</td>
                      <td>{r.recovery_time_ms} ms</td>
                      <td><code>{r.audit_event_id}</code></td>
                      <td>
                        <span className={`pill ${r.passed ? "pill-ok" : "pill-danger"}`}>
                          {r.passed ? "PASS" : "FAIL"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="grid-two">
        <div className="card">
          <h3>Immutable Audit Log (NT-4)</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Event Type</th>
                  <th>Actor</th>
                  <th>Detail</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {auditEvents.map((e) => (
                  <tr key={e.audit_id}>
                    <td><code>{e.event_type}</code></td>
                    <td>{e.actor_role}</td>
                    <td className="small">{e.detail}</td>
                    <td className="small">{new Date(e.created_at).toLocaleTimeString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>Evidence Manifest (Appendix B)</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Licence</th>
                  <th>Partition</th>
                  <th>Records</th>
                </tr>
              </thead>
              <tbody>
                {manifest.map((m) => (
                  <tr key={m.manifest_id}>
                    <td className="small">{m.source_url}</td>
                    <td>{m.licence}</td>
                    <td><span className="pill pill-neutral">{m.partition}</span></td>
                    <td className="small">{m.records_info}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
