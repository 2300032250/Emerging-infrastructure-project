import React, { useEffect, useState } from "react";
import { api } from "./api/client";
import { DecisionMakerView } from "./components/DecisionMakerView";
import { OperatorView } from "./components/OperatorView";
import { ValidationView } from "./components/ValidationView";

export default function App() {
  const [tab, setTab] = useState("decision");
  const [health, setHealth] = useState(null);

  async function refreshHealth() {
    try {
      const h = await api.getHealth();
      setHealth(h);
    } catch {
      setHealth(null);
    }
  }

  useEffect(() => {
    refreshHealth();
  }, []);

  return (
    <div className="app-shell">
      <header className="top-bar">
        <div>
          <div className="brand-tag">CLOUD-225 | Batch C2C-95 | KL University Capstone</div>
          <h1>Emerging Infrastructure Project Maturity Assessment</h1>
          <p className="subtitle">
            Sustainability-based adoption decisions independent of stars, forks, and downloads
          </p>
        </div>

        <div className="health-status">
          {health ? (
            <>
              <span className={`pill ${health.degraded_mode ? "pill-warn" : "pill-ok"}`}>
                {health.degraded_mode ? "DEGRADED MODE" : "SYSTEM HEALTHY"}
              </span>
              <span className="muted small">
                v{health.config_version} ({health.config_hash}) | {health.total_projects} projects
              </span>
            </>
          ) : (
            <span className="pill pill-danger">Backend Offline (port 8000)</span>
          )}
        </div>
      </header>

      <nav className="tab-nav">
        <button
          type="button"
          className={tab === "decision" ? "tab-active" : ""}
          onClick={() => setTab("decision")}
        >
          Decision-Maker View
        </button>
        <button
          type="button"
          className={tab === "validation" ? "tab-active" : ""}
          onClick={() => setTab("validation")}
        >
          Validation &amp; KPIs (Ch. 7)
        </button>
        <button
          type="button"
          className={tab === "operator" ? "tab-active" : ""}
          onClick={() => setTab("operator")}
        >
          Operator &amp; NT-1..NT-5 Console
        </button>
      </nav>

      <main className="main-content">
        {tab === "decision" && <DecisionMakerView onStatusChange={refreshHealth} />}
        {tab === "validation" && <ValidationView />}
        {tab === "operator" && <OperatorView onStatusChange={refreshHealth} />}
      </main>
    </div>
  );
}
