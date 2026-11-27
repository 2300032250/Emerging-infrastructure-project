import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { ContinuityGauge } from "./ContinuityGauge";

const RISK_LABELS = {
  LOW_RISK: "Low Risk",
  MODERATE_RISK: "Moderate Risk",
  HIGH_RISK: "High Risk",
  CRITICAL_SINGLE_MAINTAINER: "Critical: Single Maintainer",
};

export function DecisionMakerView({ onStatusChange }) {
  const [projects, setProjects] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [assessment, setAssessment] = useState(null);
  const [history, setHistory] = useState([]);
  const [partitionFilter, setPartitionFilter] = useState("");
  const [auditNotice, setAuditNotice] = useState("");
  const [ingestRepo, setIngestRepo] = useState("");
  const [ingestMode, setIngestMode] = useState("synthetic_fixture");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadProjects(sortBy = "sustainability_desc", partition = partitionFilter) {
    setError("");
    try {
      const data = await api.listProjects(sortBy, partition);
      setProjects(data.projects || []);
      setAuditNotice(data.audit_notice || "");
      if (!selectedId && data.projects?.length > 0) {
        setSelectedId(data.projects[0].project_id);
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadAssessment(projectId) {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const [asmt, hist] = await Promise.all([
        api.getAssessment(projectId),
        api.getAssessmentHistory(projectId),
      ]);
      setAssessment(asmt);
      setHistory(hist || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects("sustainability_desc", partitionFilter);
  }, [partitionFilter]);

  useEffect(() => {
    if (selectedId) loadAssessment(selectedId);
  }, [selectedId]);

  async function handleReassess() {
    if (!selectedId) return;
    setLoading(true);
    setError("");
    try {
      const asmt = await api.runAssessment(selectedId);
      setAssessment(asmt);
      const hist = await api.getAssessmentHistory(selectedId);
      setHistory(hist || []);
      await loadProjects("sustainability_desc", partitionFilter);
      onStatusChange?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleIngest(e) {
    e.preventDefault();
    if (!ingestRepo.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await api.ingestProject({
        repository: ingestRepo.trim(),
        mode: ingestMode,
        partition: "live",
        licence: "Apache-2.0",
      });
      setIngestRepo("");
      await loadProjects("sustainability_desc", partitionFilter);
      setSelectedId(res.project_id);
      await loadAssessment(res.project_id);
      onStatusChange?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <div className="card-header-row">
          <div>
            <h2>Repository Ingestion &amp; Assessment Request</h2>
            <p className="muted">
              Submit a cloud-infrastructure repository (<code>owner/repo</code>) via GitHub REST API or deterministic offline fixture.
            </p>
          </div>
          <span className="pill pill-info">Popularity Signals Excluded (O3)</span>
        </div>

        <form onSubmit={handleIngest} className="ingest-form">
          <input
            type="text"
            placeholder="e.g. kubernetes/ingress-nginx or custom-org/kube-proxy-lite"
            value={ingestRepo}
            onChange={(e) => setIngestRepo(e.target.value)}
            required
          />
          <select value={ingestMode} onChange={(e) => setIngestMode(e.target.value)}>
            <option value="synthetic_fixture">Offline Validated Fixture</option>
            <option value="github">Live GitHub REST API</option>
          </select>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Processing..." : "Ingest & Assess"}
          </button>
        </form>
      </div>

      {error && <div className="banner banner-danger">{error}</div>}
      {auditNotice && <div className="banner banner-warn">{auditNotice}</div>}

      <div className="grid-two">
        <div className="card">
          <div className="card-header-row">
            <h3>Sustainability Ranking</h3>
            <div className="row-actions">
              <select
                value={partitionFilter}
                onChange={(e) => setPartitionFilter(e.target.value)}
                aria-label="Partition Filter"
              >
                <option value="">All Partitions</option>
                <option value="acceptance">Acceptance (Held-Out)</option>
                <option value="dev">Dev (Training)</option>
                <option value="live">Live Ingested</option>
              </select>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => loadProjects("stars", partitionFilter)}
                title="Exercises NT-3 guard: attempts to rank by GitHub stars"
              >
                Test NT-3: Sort by Stars
              </button>
            </div>
          </div>

          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Repository</th>
                  <th>Partition</th>
                  <th>Stars (Ignored)</th>
                  <th>Continuity</th>
                  <th>Risk</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr
                    key={p.project_id}
                    className={p.project_id === selectedId ? "selected-row" : ""}
                    onClick={() => setSelectedId(p.project_id)}
                  >
                    <td>
                      <strong>{p.repository}</strong>
                      {p.popularity_mismatch_flag && (
                        <span className="pill pill-danger ml-1">Star Trap</span>
                      )}
                    </td>
                    <td>
                      <span className="pill pill-neutral">{p.partition}</span>
                    </td>
                    <td className="muted">{p.reported_stars.toLocaleString()}</td>
                    <td>
                      {p.latest_score !== null ? `${(p.latest_score * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td>
                      <span className={`pill risk-${(p.latest_risk_level || "LOW_RISK").toLowerCase()}`}>
                        {RISK_LABELS[p.latest_risk_level] || p.latest_risk_level || "Pending"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          {!assessment ? (
            <p className="muted">Select a repository from the ranking table to inspect its maturity assessment.</p>
          ) : (
            <div className="stack-sm">
              <div className="card-header-row">
                <div>
                  <h3>{assessment.repository}</h3>
                  <p className="muted small">
                    Version: <code>{assessment.input_version}</code> | Config Hash: <code>{assessment.config_hash}</code>
                  </p>
                </div>
                <button type="button" className="btn-secondary" onClick={handleReassess} disabled={loading}>
                  Re-run Assessment
                </button>
              </div>

              {assessment.is_stale && (
                <div className="banner banner-warn">
                  <strong>STALE FALLBACK (DEGRADED MODE):</strong> {assessment.stale_reason}
                </div>
              )}

              {assessment.popularity_trap_warning && (
                <div className="banner banner-danger">
                  <strong>NT-1 Alert:</strong> {assessment.popularity_trap_warning}
                </div>
              )}

              <div className="assessment-hero">
                <ContinuityGauge
                  percent={assessment.continuity_percent}
                  riskLevel={assessment.risk_level}
                />
                <div className="hero-text">
                  <span className={`pill risk-${assessment.risk_level.toLowerCase()}`}>
                    {RISK_LABELS[assessment.risk_level] || assessment.risk_level}
                  </span>
                  <p className="explanation">{assessment.plain_language_explanation}</p>
                </div>
              </div>

              <h4>Top 3 Contributing Indicators (O4 Explainability)</h4>
              <div className="factors-grid">
                {assessment.top_contributors.map((factor) => (
                  <div key={factor.indicator} className={`factor-card factor-${factor.impact}`}>
                    <div className="factor-top">
                      <strong>{factor.label}</strong>
                      <span className={`pill ${factor.impact === "positive" ? "pill-ok" : "pill-danger"}`}>
                        {factor.impact === "positive" ? "Supports" : "Risk Driver"}
                      </span>
                    </div>
                    <p className="small muted">{factor.detail}</p>
                  </div>
                ))}
              </div>

              <h4>O2 Reference &amp; O3 Sustainability Indicators</h4>
              <div className="metrics-grid">
                <div className="metric-box">
                  <span>Top-Contributor Share (O2)</span>
                  <strong>{(assessment.indicators.top_contributor_share * 100).toFixed(1)}%</strong>
                </div>
                <div className="metric-box">
                  <span>Maintainer Set Size (O2)</span>
                  <strong>{assessment.indicators.maintainer_set_size}</strong>
                </div>
                <div className="metric-box">
                  <span>Release Interval CV (O2)</span>
                  <strong>{assessment.indicators.release_interval_cv}</strong>
                </div>
                <div className="metric-box">
                  <span>Longest Release Gap (O2)</span>
                  <strong>{assessment.indicators.longest_release_gap_months} mo</strong>
                </div>
                <div className="metric-box">
                  <span>Contributor Retention (O3)</span>
                  <strong>{(assessment.indicators.contributor_retention * 100).toFixed(1)}%</strong>
                </div>
                <div className="metric-box">
                  <span>Issue Response Median (O3)</span>
                  <strong>{assessment.indicators.issue_responsiveness_hours} h</strong>
                </div>
                <div className="metric-box">
                  <span>PR Throughput Median (O3)</span>
                  <strong>{assessment.indicators.pr_throughput_hours} h</strong>
                </div>
                <div className="metric-box">
                  <span>Maintainer Trend Slope (O3)</span>
                  <strong>{assessment.indicators.maintainer_inactivity_slope}</strong>
                </div>
                <div className="metric-box">
                  <span>Maintainer Rubric (KPI-2)</span>
                  <strong>{assessment.indicators.maintainer_concentration_score} / 100</strong>
                </div>
                <div className="metric-box">
                  <span>Release Rubric (KPI-3)</span>
                  <strong>{assessment.indicators.release_continuity_score} / 100</strong>
                </div>
              </div>

              {history.length > 0 && (
                <>
                  <h4>Append-Only Assessment History (NT-4 Immutable)</h4>
                  <div className="table-scroll small-table">
                    <table>
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>Score</th>
                          <th>Risk</th>
                          <th>Stale</th>
                          <th>Timestamp</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.slice(0, 5).map((h) => (
                          <tr key={h.assessment_id}>
                            <td><code>{h.assessment_id}</code></td>
                            <td>{(h.score * 100).toFixed(1)}%</td>
                            <td>{h.risk_level}</td>
                            <td>{h.is_stale ? "Yes" : "No"}</td>
                            <td>{new Date(h.created_at).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
