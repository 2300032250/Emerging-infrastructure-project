import React, { useEffect, useState } from "react";
import { api } from "../api/client";

export function ValidationView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadEval() {
    setLoading(true);
    setError("");
    try {
      const res = await api.getEvaluationSummary(30);
      setData(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadEval();
  }, []);

  if (loading && !data) return <div className="card">Running Chapter 7 acceptance evaluation...</div>;
  if (error) return <div className="banner banner-danger">{error}</div>;
  if (!data) return null;

  const { kpis, ablation, sensitivity, latency_distribution, projects } = data;

  return (
    <div className="stack">
      <div className="card">
        <div className="card-header-row">
          <div>
            <h2>Chapter 7 Validation &amp; KPI Scorecard (Held-Out Acceptance Partition)</h2>
            <p className="muted">
              Evaluated under frozen AC-4 envelope: {data.sample_size} held-out projects, {data.trials} monotonic latency trials after warm-up.
            </p>
          </div>
          <button type="button" className="btn-primary" onClick={loadEval} disabled={loading}>
            {loading ? "Running..." : "Re-run AC-1..AC-4 Benchmark"}
          </button>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>KPI</th>
                <th>Measure</th>
                <th>Target / Pass Rule</th>
                <th>O2 Reference</th>
                <th>Achieved</th>
                <th>Status</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {kpis.map((k) => (
                <tr key={k.kpi_id}>
                  <td><strong>{k.kpi_id}</strong></td>
                  <td>{k.measure}</td>
                  <td><code>{k.target}</code></td>
                  <td>{k.o2_reference} {k.unit}</td>
                  <td><strong>{k.achieved} {k.unit}</strong></td>
                  <td>
                    <span className={`pill ${k.passed ? "pill-ok" : "pill-danger"}`}>
                      {k.passed ? "PASS" : "FAIL"}
                    </span>
                  </td>
                  <td className="muted small">{k.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid-two">
        <div className="card">
          <h3>Ablation: O2 Reference vs O3 Contribution vs O4</h3>
          <div className="bar-list">
            {ablation.map((row) => (
              <div key={row.variant} className="bar-item">
                <div className="bar-label-row">
                  <span>{row.variant}</span>
                  <strong>{row.accuracy_pct}%</strong>
                </div>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${row.accuracy_pct}%` }} />
                </div>
              </div>
            ))}
          </div>

          <h4 className="mt-2">Observation Window &amp; Cut-Off Sensitivity</h4>
          <table>
            <thead>
              <tr>
                <th>Window</th>
                <th>Cut-Off Shift</th>
                <th>Held-Out Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {sensitivity.map((s, idx) => (
                <tr key={idx}>
                  <td>{s.window_months} months</td>
                  <td>{s.cutoff_shift_days} days</td>
                  <td><strong>{s.accuracy_pct}%</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Latency Distribution (p50, p95, p99)</h3>
          <div className="metrics-grid">
            <div className="metric-box">
              <span>p50 Latency</span>
              <strong>{latency_distribution.p50_ms} ms</strong>
            </div>
            <div className="metric-box">
              <span>p95 Latency (KPI-6)</span>
              <strong>{latency_distribution.p95_ms} ms</strong>
            </div>
            <div className="metric-box">
              <span>p99 Latency</span>
              <strong>{latency_distribution.p99_ms} ms</strong>
            </div>
            <div className="metric-box">
              <span>O2 Baseline p95</span>
              <strong>{latency_distribution.o2_p95_ms} ms</strong>
            </div>
          </div>

          <h4 className="mt-2">Per-Trial Latency Profile (First 30 Trials, ms)</h4>
          <div className="spark-bars">
            {latency_distribution.samples_ms.map((val, i) => {
              const maxVal = Math.max(...latency_distribution.samples_ms, 1);
              const pct = Math.max(8, (val / maxVal) * 100);
              return (
                <div
                  key={i}
                  className="spark-bar"
                  style={{ height: `${pct}%` }}
                  title={`Trial ${i + 1}: ${val} ms`}
                />
              );
            })}
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Held-Out Acceptance Projects: O2 vs O3+O4 Outcomes</h3>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Repository</th>
                <th>Stars (Excluded)</th>
                <th>Actual Outcome</th>
                <th>O2 Baseline P(active)</th>
                <th>O3+O4 P(active)</th>
                <th>Risk Tier</th>
                <th>O4 Match</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.project_id}>
                  <td><strong>{p.repository}</strong></td>
                  <td className="muted">{p.reported_stars.toLocaleString()}</td>
                  <td>
                    <span className={`pill ${p.ground_truth === "active" ? "pill-ok" : "pill-warn"}`}>
                      {p.ground_truth}
                    </span>
                  </td>
                  <td>{(p.o2_baseline_prob * 100).toFixed(1)}%</td>
                  <td><strong>{(p.o3_o4_prob * 100).toFixed(1)}%</strong></td>
                  <td>{p.o3_o4_risk_level}</td>
                  <td>
                    <span className={`pill ${p.o4_correct ? "pill-ok" : "pill-danger"}`}>
                      {p.o4_correct ? "Correct" : "Miss"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
