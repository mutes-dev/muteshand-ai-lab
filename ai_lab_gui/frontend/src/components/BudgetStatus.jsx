/**
 * BUDGET STATUS — ISSUE-094C (Modal Control Surface)
 *
 * Compact status bar with obvious "LLM Settings" button.
 * Opens a full modal panel for runtime LLM routing/budget control.
 */

import { useState, useEffect, useCallback } from "react";
import { api } from "../api.js";

const MODE_DISPLAY = {
  strict_local: "Local Only",
  local_first: "Local First",
  dev_fast: "Dev Fast",
};

const ROUTE_DISPLAY = {
  cloud_allowed: "Cloud Allowed",
  local_only: "Local Only",
};

const ROUTE_COLOR = {
  cloud_allowed: "#22c55e",
  local_only: "#94a3b8",
};

const KEY_STATUS_DISPLAY = {
  not_configured: "Not configured",
  not_refreshed: "Not refreshed",
  available: "Available",
  missing_fields: "Missing fields",
  error: "Error",
};

const CATALOGUE_STATUS_DISPLAY = {
  not_loaded: "Not loaded",
  available: "Available",
  error: "Error",
};

function poolFromString(s) {
  if (!s) return [];
  return s.split(",").map((m) => m.trim()).filter(Boolean);
}

function poolToString(arr) {
  return (arr || []).join(", ");
}

export default function BudgetStatus() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [error, setError] = useState(null);
  const [applyLoading, setApplyLoading] = useState(false);
  const [form, setForm] = useState({});
  const [recentUsage, setRecentUsage] = useState([]);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.llmBudgetStatus();
      setStatus(data);
      const defaults = data.openrouter?.default_pools || {};
      const getPool = (role) => {
        const runtimePool = data.providers?.[role]?.pool || [];
        if (runtimePool.length > 0) return poolToString(runtimePool);
        const def = defaults[role] || [];
        return poolToString(def);
      };
      setForm({
        mode: data.mode || "local_first",
        planner_provider: data.providers?.planner?.provider || "ollama",
        agent_provider: data.providers?.agent?.provider || "ollama",
        formatter_provider: data.providers?.formatter?.provider || "ollama",
        validator_provider: data.providers?.validator?.provider || "ollama",
        planner_pool: getPool("planner"),
        agent_pool: getPool("agent"),
        formatter_pool: getPool("formatter"),
        validator_pool: getPool("validator"),
        daily_budget_usd: String(data.budget?.daily_limit_usd ?? 0.25),
        monthly_budget_usd: String(data.budget?.monthly_limit_usd ?? 5.0),
        credit_reserve_usd: String(data.budget?.credit_reserve_usd ?? 2.0),
        fallback_on_budget: data.budget?.fallback_on_budget !== false,
        fallback_provider: data.fallback_provider || "ollama",
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleRefresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.llmBudgetRefresh();
      setStatus(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async () => {
    setApplyLoading(true);
    setError(null);
    try {
      const payload = {
        ...form,
        daily_budget_usd: parseFloat(form.daily_budget_usd) || 0,
        monthly_budget_usd: parseFloat(form.monthly_budget_usd) || 0,
        credit_reserve_usd: parseFloat(form.credit_reserve_usd) || 0,
        fallback_on_budget: !!form.fallback_on_budget,
      };
      const data = await api.llmSettingsUpdate(payload);
      setStatus(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setApplyLoading(false);
    }
  };

  const handleResetLocal = async () => {
    setApplyLoading(true);
    setError(null);
    try {
      const data = await api.llmSettingsResetLocal();
      setStatus(data);
      const defaults = data.openrouter?.default_pools || {};
      const getPool = (role) => {
        const runtimePool = data.providers?.[role]?.pool || [];
        if (runtimePool.length > 0) return poolToString(runtimePool);
        const def = defaults[role] || [];
        return poolToString(def);
      };
      setForm({
        mode: data.mode || "local_first",
        planner_provider: data.providers?.planner?.provider || "ollama",
        agent_provider: data.providers?.agent?.provider || "ollama",
        formatter_provider: data.providers?.formatter?.provider || "ollama",
        validator_provider: data.providers?.validator?.provider || "ollama",
        planner_pool: getPool("planner"),
        agent_pool: getPool("agent"),
        formatter_pool: getPool("formatter"),
        validator_pool: getPool("validator"),
        daily_budget_usd: String(data.budget?.daily_limit_usd ?? 0.25),
        monthly_budget_usd: String(data.budget?.monthly_limit_usd ?? 5.0),
        credit_reserve_usd: String(data.budget?.credit_reserve_usd ?? 2.0),
        fallback_on_budget: data.budget?.fallback_on_budget !== false,
        fallback_provider: data.fallback_provider || "ollama",
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setApplyLoading(false);
    }
  };

  const fetchRecentUsage = useCallback(async () => {
    try {
      const data = await api.llmUsageRecent(10);
      setRecentUsage(data.entries || []);
    } catch (e) {
      // Silently ignore — this is observational only
    }
  }, []);

  useEffect(() => {
    if (modalOpen) {
      fetchRecentUsage();
    }
  }, [modalOpen, fetchRecentUsage]);

  const updateField = (key, value) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const addModel = (role, modelId) => {
    if (!modelId) return;
    const current = poolFromString(form[`${role}_pool`] || "");
    if (current.includes(modelId)) return;
    const next = [...current, modelId];
    updateField(`${role}_pool`, poolToString(next));
  };

  const removeModel = (role, modelId) => {
    const current = poolFromString(form[`${role}_pool`] || "");
    const next = current.filter((m) => m !== modelId);
    updateField(`${role}_pool`, poolToString(next));
  };

  const applyPreset = (preset) => {
    const defaults = status?.openrouter?.default_pools || {};
    if (preset === "local_ollama") {
      setForm((prev) => ({
        ...prev,
        mode: "local_first",
        planner_provider: "ollama",
        agent_provider: "ollama",
        formatter_provider: "ollama",
        validator_provider: "ollama",
        planner_pool: poolToString(defaults.planner || []),
        agent_pool: poolToString(defaults.agent || []),
        formatter_pool: poolToString(defaults.formatter || []),
        validator_pool: poolToString(defaults.validator || []),
      }));
    } else if (preset === "cloud_planner") {
      setForm((prev) => ({
        ...prev,
        mode: "dev_fast",
        planner_provider: "openrouter",
        agent_provider: "ollama",
        formatter_provider: "ollama",
        validator_provider: "ollama",
        planner_pool: poolToString(defaults.planner || []),
        agent_pool: poolToString(defaults.agent || []),
        formatter_pool: poolToString(defaults.formatter || []),
        validator_pool: poolToString(defaults.validator || []),
      }));
    } else if (preset === "cloud_planner_agent") {
      setForm((prev) => ({
        ...prev,
        mode: "dev_fast",
        planner_provider: "openrouter",
        agent_provider: "openrouter",
        formatter_provider: "ollama",
        validator_provider: "ollama",
        planner_pool: poolToString(defaults.planner || []),
        agent_pool: poolToString(defaults.agent || []),
        formatter_pool: poolToString(defaults.formatter || []),
        validator_pool: poolToString(defaults.validator || []),
      }));
    } else if (preset === "strict_local") {
      setForm((prev) => ({
        ...prev,
        mode: "strict_local",
        planner_provider: "ollama",
        agent_provider: "ollama",
        formatter_provider: "ollama",
        validator_provider: "ollama",
        planner_pool: poolToString(defaults.planner || []),
        agent_pool: poolToString(defaults.agent || []),
        formatter_pool: poolToString(defaults.formatter || []),
        validator_pool: poolToString(defaults.validator || []),
      }));
    }
  };

  if (!status && !error) {
    return (
      <span style={{ fontSize: "0.75rem", color: "#94a3b8", padding: "4px 0" }}>
        LLM Settings: loading...
      </span>
    );
  }

  if (error && !status) {
    return (
      <span style={{ fontSize: "0.75rem", color: "#ef4444", padding: "4px 0" }}>
        LLM Settings: unavailable
      </span>
    );
  }

  const mode = status.mode || "local_first";
  const routeStatus = status.current_route_status || "local_only";
  const budget = status.budget || {};
  const openrouter = status.openrouter || {};
  const freeModels = openrouter.free_models || [];

  const routeColor = ROUTE_COLOR[routeStatus] || "#94a3b8";
  const routeLabel = ROUTE_DISPLAY[routeStatus] || routeStatus;
  const modeLabel = MODE_DISPLAY[mode] || mode;

  const warnings = [];
  if (openrouter.configured && openrouter.key_status === "not_refreshed") {
    warnings.push("OpenRouter key is configured but status has not been refreshed.");
  }
  if (openrouter.key_status === "missing_fields") {
    warnings.push(openrouter.key_error_summary || "OpenRouter key endpoint responded, but limit/usage fields were not available or were not parsed.");
  }
  if (openrouter.key_status === "error" && openrouter.key_error_summary) {
    warnings.push(`OpenRouter key error: ${openrouter.key_error_summary}`);
  }
  ["planner", "agent", "formatter", "validator"].forEach((r) => {
    const prov = form[`${r}_provider`];
    const pool = (form[`${r}_pool`] || "").trim();
    if (prov === "openrouter" && !pool) {
      warnings.push(`${r.charAt(0).toUpperCase() + r.slice(1)} uses OpenRouter but has no model pool. Add models.`);
    }
  });
  const orKeyMissing = !openrouter.configured && ["planner", "agent", "formatter", "validator"].some(
    (r) => form[`${r}_provider`] === "openrouter"
  );
  if (orKeyMissing) {
    warnings.push("OpenRouter provider selected but API key is not configured. Cloud calls will fallback to Ollama.");
  }

  const budgetNeg =
    parseFloat(form.daily_budget_usd) < 0 ||
    parseFloat(form.monthly_budget_usd) < 0 ||
    parseFloat(form.credit_reserve_usd) < 0;

  const inputStyle = {
    background: "#1e293b",
    color: "#e2e8f0",
    border: "1px solid #334155",
    borderRadius: "4px",
    padding: "6px 10px",
    fontSize: "0.85rem",
    width: "100%",
    fontFamily: "inherit",
  };

  const selectStyle = { ...inputStyle, width: "auto", minWidth: "140px" };
  const labelStyle = { fontSize: "0.8rem", color: "#94a3b8", marginBottom: "4px", display: "block", fontWeight: 500 };
  const rowStyle = { display: "flex", gap: "14px", alignItems: "flex-end", marginBottom: "10px", flexWrap: "wrap" };
  const sectionHeader = { fontWeight: 700, fontSize: "0.95rem", margin: "16px 0 8px", color: "#e2e8f0", borderBottom: "1px solid #334155", paddingBottom: "4px" };
  const btnStyle = { padding: "8px 16px", borderRadius: "6px", border: "1px solid #334155", background: "#1e293b", color: "#e2e8f0", cursor: "pointer", fontSize: "0.85rem", fontWeight: 500 };
  const btnPrimary = { ...btnStyle, background: "#2563eb", borderColor: "#2563eb", color: "#fff" };
  const btnDanger = { ...btnStyle, background: "#dc2626", borderColor: "#dc2626", color: "#fff" };
  const presetBtnStyle = { ...btnStyle, padding: "6px 12px", fontSize: "0.8rem", borderColor: "#475569" };

  const Chip = ({ label, onRemove }) => (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        padding: "2px 8px",
        borderRadius: "9999px",
        background: "#1e293b",
        border: "1px solid #334155",
        color: "#e2e8f0",
        fontSize: "0.8rem",
        cursor: "default",
      }}
    >
      {label}
      <button
        onClick={onRemove}
        style={{ background: "transparent", border: "none", color: "#94a3b8", cursor: "pointer", fontSize: "0.75rem", padding: 0, lineHeight: 1 }}
        title="Remove"
      >
        ×
      </button>
    </span>
  );

  const ModelChipSelector = ({ role }) => {
    const [selected, setSelected] = useState("");
    const pool = poolFromString(form[`${role}_pool`] || "");
    const available = freeModels.filter((m) => !pool.includes(m.id));
    return (
      <div style={{ marginBottom: "12px" }}>
        <div style={{ marginBottom: "8px", display: "flex", gap: "6px", flexWrap: "wrap" }}>
          {pool.map((m) => (
            <Chip key={m} label={m} onRemove={() => removeModel(role, m)} />
          ))}
          {pool.length === 0 && (
            <span style={{ fontSize: "0.8rem", color: "#64748b", fontStyle: "italic" }}>No models in pool</span>
          )}
        </div>
        <div style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
          <select
            style={selectStyle}
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">{`Add free model to ${role} pool`}</option>
            {available.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
          <button
            style={{ ...presetBtnStyle, background: "#0f172a" }}
            onClick={() => { if (selected) { addModel(role, selected); setSelected(""); } }}
            disabled={!selected}
          >
            Add
          </button>
        </div>
        <label style={labelStyle}>{role.charAt(0).toUpperCase() + role.slice(1)} Pool (advanced edit)</label>
        <textarea
          style={{ ...inputStyle, minHeight: "48px", resize: "vertical" }}
          value={form[`${role}_pool`] || ""}
          onChange={(e) => updateField(`${role}_pool`, e.target.value)}
          placeholder="model-id-1, model-id-2, model-id-3"
          rows={2}
        />
      </div>
    );
  };

  const routeSummaryParts = [];
  if (routeStatus === "cloud_allowed") {
    const activeRoles = ["planner", "agent", "formatter", "validator"].filter(
      (r) => status.providers?.[r]?.effective_provider === "openrouter"
    );
    routeSummaryParts.push("Route: Cloud Allowed");
    routeSummaryParts.push("Cloud Active: Yes");
    activeRoles.forEach((r) => routeSummaryParts.push(`${r.charAt(0).toUpperCase() + r.slice(1)}: OpenRouter`));
  } else {
    routeSummaryParts.push("Route: Local Only");
    routeSummaryParts.push("Cloud Active: No");
    if (status.cloud_block_reason) {
      routeSummaryParts.push(`Reason: ${status.cloud_block_reason}`);
    }
  }

  return (
    <>
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "10px",
          flexWrap: "wrap",
          fontSize: "0.85rem",
          color: "#cbd5e1",
        }}
      >
        <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: routeColor, display: "inline-block", flexShrink: 0 }} />
        <span style={{ color: routeColor, fontWeight: 700 }}>LLM: {modeLabel}</span>
        <span style={{ color: "#64748b" }}>
          {(() => {
            const st = openrouter.status;
            const ks = openrouter.key_status;
            if (st === "available" && ks !== "available") return `OpenRouter Key: ${KEY_STATUS_DISPLAY[ks] || ks}`;
            return `OpenRouter: ${st ? (KEY_STATUS_DISPLAY[st] || st) : "—"}`;
          })()}
        </span>
        <span style={{ color: "#64748b" }}>
          Budget: ${(budget.monthly_used_usd ?? 0).toFixed(2)} / ${(budget.monthly_limit_usd ?? 5).toFixed(2)} est.
        </span>
        <span style={{ color: routeColor, fontWeight: 600 }}>{routeLabel}</span>
        <button
          onClick={() => setModalOpen(true)}
          style={{
            padding: "4px 14px",
            borderRadius: "9999px",
            border: "1px solid #3b82f6",
            background: "#1d4ed8",
            color: "#fff",
            cursor: "pointer",
            fontSize: "0.8rem",
            fontWeight: 600,
            whiteSpace: "nowrap",
          }}
        >
          LLM Settings
        </button>
      </div>

      {modalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(0,0,0,0.7)",
            padding: "16px",
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setModalOpen(false);
          }}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: "10px",
              width: "100%",
              maxWidth: "720px",
              maxHeight: "90vh",
              overflowY: "auto",
              color: "#e2e8f0",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "14px 18px",
                borderBottom: "1px solid #334155",
                position: "sticky",
                top: 0,
                background: "#0f172a",
                zIndex: 1,
              }}
            >
              <h2 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "#f8fafc" }}>LLM / Budget Settings</h2>
              <button
                onClick={() => setModalOpen(false)}
                style={{ background: "transparent", border: "none", color: "#94a3b8", fontSize: "1.2rem", cursor: "pointer" }}
                title="Close"
              >
                ×
              </button>
            </div>

            <div style={{ padding: "14px 18px" }}>
              {error && (
                <div style={{ fontSize: "0.8rem", color: "#ef4444", marginBottom: "10px", padding: "8px", background: "#1e293b", borderRadius: "4px" }}>
                  Error: {error}
                </div>
              )}

              <div style={{ marginBottom: "14px" }}>
                <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginBottom: "6px", fontWeight: 600 }}>Quick Presets</div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <button style={presetBtnStyle} onClick={() => applyPreset("local_ollama")}>Local/Ollama Only</button>
                  <button style={presetBtnStyle} onClick={() => applyPreset("cloud_planner")}>Free Cloud Planner Only</button>
                  <button style={presetBtnStyle} onClick={() => applyPreset("cloud_planner_agent")}>Free Cloud Planner + Agent</button>
                  <button style={presetBtnStyle} onClick={() => applyPreset("strict_local")}>Strict Local</button>
                </div>
                <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "4px" }}>
                  Presets update the form only. You must still click Apply Runtime Settings.
                </div>
              </div>

              <div style={{ fontSize: "0.85rem", color: "#cbd5e1", marginBottom: "12px", padding: "8px", background: "#1e293b", borderRadius: "6px", border: "1px solid #334155" }}>
                {routeSummaryParts.map((part, i) => (
                  <span key={i} style={{ display: "inline-block", marginRight: "12px", marginBottom: "2px" }}>{part}</span>
                ))}
              </div>

              {warnings.length > 0 && (
                <div style={{ marginBottom: "12px" }}>
                  {warnings.map((w, i) => (
                    <div key={i} style={{ fontSize: "0.8rem", color: "#f59e0b", marginBottom: "4px" }}>⚠ {w}</div>
                  ))}
                </div>
              )}
              {budgetNeg && (
                <div style={{ fontSize: "0.8rem", color: "#ef4444", marginBottom: "12px" }}>⚠ Budget values must not be negative.</div>
              )}

              <div style={sectionHeader}>Routing</div>
              <div style={rowStyle}>
                <div>
                  <label style={labelStyle}>Mode</label>
                  <select style={selectStyle} value={form.mode || "local_first"} onChange={(e) => updateField("mode", e.target.value)}>
                    <option value="strict_local">strict_local</option>
                    <option value="local_first">local_first</option>
                    <option value="dev_fast">dev_fast</option>
                  </select>
                </div>
              </div>
              <div style={rowStyle}>
                {["planner", "agent", "formatter", "validator"].map((role) => (
                  <div key={role}>
                    <label style={labelStyle}>{role.charAt(0).toUpperCase() + role.slice(1)} Provider</label>
                    <select style={selectStyle} value={form[`${role}_provider`] || "ollama"} onChange={(e) => updateField(`${role}_provider`, e.target.value)}>
                      <option value="ollama">Ollama</option>
                      <option value="openrouter">OpenRouter</option>
                    </select>
                  </div>
                ))}
              </div>

              <div style={sectionHeader}>Model Pools</div>
              <ModelChipSelector role="planner" />
              <ModelChipSelector role="agent" />
              <div style={{ marginBottom: "10px" }}>
                <label style={labelStyle}>Formatter OpenRouter Pool</label>
                <textarea
                  style={{ ...inputStyle, minHeight: "48px", resize: "vertical" }}
                  value={form.formatter_pool || ""}
                  onChange={(e) => updateField("formatter_pool", e.target.value)}
                  placeholder="model-id-1, model-id-2, model-id-3"
                  rows={2}
                />
              </div>
              <div style={{ marginBottom: "10px" }}>
                <label style={labelStyle}>Validator OpenRouter Pool</label>
                <textarea
                  style={{ ...inputStyle, minHeight: "48px", resize: "vertical" }}
                  value={form.validator_pool || ""}
                  onChange={(e) => updateField("validator_pool", e.target.value)}
                  placeholder="model-id-1, model-id-2, model-id-3"
                  rows={2}
                />
              </div>

              <div style={sectionHeader}>MutesHand Cloud Budget Guard</div>
              <div style={{ fontSize: "0.8rem", color: "#64748b", marginBottom: "10px" }}>
                MutesHand budget usage is estimated from the local LLM usage ledger. OpenRouter key remaining/usage is fetched from OpenRouter when the backend detects MH_OPENROUTER_API_KEY and refresh succeeds.
              </div>

              <div style={{ ...sectionHeader, fontSize: "0.9rem", marginTop: "12px" }}>A. Local Estimated Ledger Usage</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px", fontSize: "0.8rem", color: "#94a3b8", marginBottom: "10px" }}>
                <div><strong style={{ color: "#cbd5e1" }}>Today:</strong> ${(budget.daily_used_usd ?? 0).toFixed(4)}</div>
                <div><strong style={{ color: "#cbd5e1" }}>This month:</strong> ${(budget.monthly_used_usd ?? 0).toFixed(4)}</div>
              </div>

              <div style={{ ...sectionHeader, fontSize: "0.9rem", marginTop: "12px" }}>B. MutesHand Configured Guard Limits</div>
              <div style={rowStyle}>
                <div>
                  <label style={labelStyle}>Daily cloud limit (USD)</label>
                  <input type="number" step="0.01" style={{ ...inputStyle, width: "120px" }} value={form.daily_budget_usd ?? "0.25"} onChange={(e) => updateField("daily_budget_usd", e.target.value)} />
                </div>
                <div>
                  <label style={labelStyle}>Monthly cloud limit (USD)</label>
                  <input type="number" step="0.01" style={{ ...inputStyle, width: "120px" }} value={form.monthly_budget_usd ?? "5.00"} onChange={(e) => updateField("monthly_budget_usd", e.target.value)} />
                </div>
                <div>
                  <label style={labelStyle}>Credit reserve (USD)</label>
                  <input type="number" step="0.01" style={{ ...inputStyle, width: "120px" }} value={form.credit_reserve_usd ?? "2.00"} onChange={(e) => updateField("credit_reserve_usd", e.target.value)} />
                </div>
              </div>
              <div style={rowStyle}>
                <div>
                  <label style={labelStyle}>Fallback Provider</label>
                  <select style={selectStyle} value={form.fallback_provider || "ollama"} onChange={(e) => updateField("fallback_provider", e.target.value)}>
                    <option value="ollama">Ollama</option>
                  </select>
                </div>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.85rem", color: "#cbd5e1" }}>
                  <input type="checkbox" checked={!!form.fallback_on_budget} onChange={(e) => updateField("fallback_on_budget", e.target.checked)} />
                  Fallback on budget reached
                </label>
              </div>

              <div style={sectionHeader}>OpenRouter Model Catalogue</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px", fontSize: "0.8rem", color: "#94a3b8", marginBottom: "12px" }}>
                <div><strong style={{ color: "#cbd5e1" }}>Catalogue status:</strong> {CATALOGUE_STATUS_DISPLAY[openrouter.catalogue_status] || openrouter.catalogue_status || "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>Free models available:</strong> {openrouter.free_models_available ?? "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>Last catalogue refresh:</strong> {openrouter.last_catalogue_refresh_iso || "—"}</div>
                {openrouter.catalogue_error_summary && (
                  <div><strong style={{ color: "#ef4444" }}>Catalogue error:</strong> {openrouter.catalogue_error_summary}</div>
                )}
              </div>

              <div style={sectionHeader}>OpenRouter Key / Account</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px", fontSize: "0.8rem", color: "#94a3b8", marginBottom: "12px" }}>
                <div><strong style={{ color: "#cbd5e1" }}>Key detected by backend:</strong> {openrouter.key_detected ? "Yes" : "No"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>Key status:</strong> {KEY_STATUS_DISPLAY[openrouter.key_status] || openrouter.key_status || "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>OpenRouter key limit:</strong> {openrouter.limit != null ? `$${Number(openrouter.limit).toFixed(2)}` : "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>OpenRouter key remaining:</strong> {openrouter.limit_remaining != null ? `$${Number(openrouter.limit_remaining).toFixed(2)}` : "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>OpenRouter usage daily:</strong> {openrouter.usage_daily != null ? `$${Number(openrouter.usage_daily).toFixed(2)}` : "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>OpenRouter usage monthly:</strong> {openrouter.usage_monthly != null ? `$${Number(openrouter.usage_monthly).toFixed(2)}` : "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>Free models available:</strong> {openrouter.free_models_available ?? "—"}</div>
                <div><strong style={{ color: "#cbd5e1" }}>Last key refresh:</strong> {openrouter.last_key_refresh_iso || "—"}</div>
              </div>
              {openrouter.key_status === "missing_fields" && (
                <div style={{ fontSize: "0.8rem", color: "#f59e0b", marginBottom: "12px", padding: "8px", background: "#1e293b", borderRadius: "4px" }}>
                  {openrouter.key_error_summary || "OpenRouter key endpoint responded, but limit/usage fields were not available or were not parsed."}
                </div>
              )}
              {openrouter.key_status === "error" && openrouter.key_error_summary && (
                <div style={{ fontSize: "0.8rem", color: "#ef4444", marginBottom: "12px", padding: "8px", background: "#1e293b", borderRadius: "4px" }}>
                  OpenRouter key error: {openrouter.key_error_summary}
                </div>
              )}
              {!openrouter.key_detected && (
                <div style={{ fontSize: "0.8rem", color: "#f59e0b", marginBottom: "12px", padding: "8px", background: "#1e293b", borderRadius: "4px" }}>
                  Backend does not see MH_OPENROUTER_API_KEY. Restart backend/Windsurf after setting the Windows user environment variable.
                </div>
              )}

              <div style={sectionHeader}>Recent LLM Calls</div>
              {recentUsage.length === 0 && (
                <div style={{ fontSize: "0.8rem", color: "#64748b", marginBottom: "12px" }}>No recent calls recorded.</div>
              )}
              {recentUsage.length > 0 && (
                <div style={{ overflowX: "auto", marginBottom: "14px" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.75rem", color: "#cbd5e1" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid #334155" }}>
                        <th style={{ textAlign: "left", padding: "4px 6px", color: "#94a3b8" }}>Time</th>
                        <th style={{ textAlign: "left", padding: "4px 6px", color: "#94a3b8" }}>Role</th>
                        <th style={{ textAlign: "left", padding: "4px 6px", color: "#94a3b8" }}>Provider</th>
                        <th style={{ textAlign: "left", padding: "4px 6px", color: "#94a3b8" }}>Model</th>
                        <th style={{ textAlign: "left", padding: "4px 6px", color: "#94a3b8" }}>Status</th>
                        <th style={{ textAlign: "left", padding: "4px 6px", color: "#94a3b8" }}>Cost</th>
                        <th style={{ textAlign: "left", padding: "4px 6px", color: "#94a3b8" }}>Route</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentUsage.map((entry, i) => (
                        <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                          <td style={{ padding: "4px 6px", whiteSpace: "nowrap" }}>{entry.timestamp_iso ? new Date(entry.timestamp_iso).toLocaleTimeString() : "—"}</td>
                          <td style={{ padding: "4px 6px" }}>{entry.caller_role || "—"}</td>
                          <td style={{ padding: "4px 6px" }}>{entry.provider || "—"}</td>
                          <td style={{ padding: "4px 6px", maxWidth: "160px", overflow: "hidden", textOverflow: "ellipsis" }} title={entry.model || ""}>{entry.model || "—"}</td>
                          <td style={{ padding: "4px 6px" }}>
                            <span style={{ color: entry.status === "success" ? "#22c55e" : "#ef4444" }}>{entry.status}</span>
                            {entry.fallback_used ? <span style={{ color: "#f59e0b", marginLeft: "4px" }}>(fb)</span> : null}
                          </td>
                          <td style={{ padding: "4px 6px" }}>${(entry.estimated_cost_usd ?? 0).toFixed(4)}</td>
                          <td style={{ padding: "4px 6px" }}>{entry.route_reason || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div style={{ fontSize: "0.75rem", color: "#64748b", marginBottom: "14px" }}>
                The OpenRouter API key is read from the backend environment. It is never displayed, transmitted, or editable in this interface.
              </div>

              <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", borderTop: "1px solid #334155", paddingTop: "14px" }}>
                <button style={btnPrimary} onClick={handleApply} disabled={applyLoading || budgetNeg}>{applyLoading ? "Applying…" : "Apply Runtime Settings"}</button>
                <button style={btnStyle} onClick={handleRefresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh OpenRouter Status"}</button>
                <button style={btnDanger} onClick={handleResetLocal} disabled={applyLoading}>Reset to Local/Ollama Defaults</button>
                <button style={btnStyle} onClick={() => setModalOpen(false)}>Close</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
