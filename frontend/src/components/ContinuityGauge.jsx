import React from "react";

export function ContinuityGauge({ percent, riskLevel }) {
  const clamped = Math.max(0, Math.min(100, percent || 0));
  const radius = 58;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;

  const colorMap = {
    LOW_RISK: "#10b981",
    MODERATE_RISK: "#f59e0b",
    HIGH_RISK: "#ef4444",
    CRITICAL_SINGLE_MAINTAINER: "#dc2626",
  };
  const strokeColor = colorMap[riskLevel] || "#38bdf8";

  return (
    <div className="gauge-wrap">
      <svg width="150" height="150" viewBox="0 0 150 150">
        <circle
          cx="75"
          cy="75"
          r={radius}
          fill="none"
          stroke="#1e293b"
          strokeWidth="12"
        />
        <circle
          cx="75"
          cy="75"
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth="12"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 75 75)"
          style={{ transition: "stroke-dashoffset 0.4s ease" }}
        />
        <text x="75" y="72" textAnchor="middle" className="gauge-value">
          {clamped.toFixed(1)}%
        </text>
        <text x="75" y="92" textAnchor="middle" className="gauge-label">
          12m Continuity
        </text>
      </svg>
    </div>
  );
}
