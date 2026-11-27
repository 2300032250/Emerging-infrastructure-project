const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const message = (data && data.detail) || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

export const api = {
  getHealth: () => request("/api/v1/health"),
  listProjects: (sortBy = "sustainability_desc", partition = "") => {
    const params = new URLSearchParams({ sort_by: sortBy });
    if (partition) params.set("partition", partition);
    return request(`/api/v1/projects?${params.toString()}`, {
      headers: { "X-Actor-Role": "decision_maker" },
    });
  },
  ingestProject: (payload) =>
    request("/api/v1/projects/ingest", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getAssessment: (projectId) =>
    request(`/api/v1/assessments/${encodeURIComponent(projectId)}`, {
      headers: { "X-Actor-Role": "decision_maker" },
    }),
  runAssessment: (projectId) =>
    request("/api/v1/assessments/run", {
      method: "POST",
      headers: { "X-Actor-Role": "decision_maker" },
      body: JSON.stringify({ project_id: projectId }),
    }),
  getAssessmentHistory: (projectId) =>
    request(`/api/v1/assessments/${encodeURIComponent(projectId)}/history`),
  getEvaluationSummary: (trials = 30) =>
    request(`/api/v1/evaluation/summary?trials=${trials}`),
  getOperatorStatus: () =>
    request("/api/v1/operator/status", {
      headers: { "X-Actor-Role": "operator" },
    }),
  injectFault: (faultType = "github_rate_limit_exhausted") =>
    request(`/api/v1/operator/fault-inject?fault_type=${encodeURIComponent(faultType)}`, {
      method: "POST",
      headers: { "X-Actor-Role": "operator" },
    }),
  recoverCheckpoints: () =>
    request("/api/v1/operator/recover", {
      method: "POST",
      headers: { "X-Actor-Role": "operator" },
    }),
  runNegativeTests: () =>
    request("/api/v1/security/negative-tests/run", {
      method: "POST",
    }),
  getAuditEvents: (limit = 35) => request(`/api/v1/audit?limit=${limit}`),
  getEvidenceManifest: () => request("/api/v1/manifest"),
};
