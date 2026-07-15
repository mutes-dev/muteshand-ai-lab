/**
 * TrustBadge — F5R additive display-only trust metadata component.
 *
 * Authority rules (frontend-only; must never be violated):
 * - Reads trust_metadata from backend result payloads only.
 * - Does NOT compute, infer, or modify trust_class.
 * - Does NOT claim authority over execution_result or lifecycle.
 * - Display-only: labels, disclaimers, coverage summary.
 * - Never shown for non-structured-data results (only renders when trust_metadata present).
 */

const TRUST_CONFIG = {
  verified: {
    label: "Verified",
    color: "#4caf50",
    bg: "rgba(76,175,80,0.10)",
    border: "rgba(76,175,80,0.30)",
    description: "Deterministic result — all requested operations executed and verified.",
  },
  advisory: {
    label: "Advisory",
    color: "#f5a623",
    bg: "rgba(245,166,35,0.10)",
    border: "rgba(245,166,35,0.30)",
    description: "AI-assisted interpretation. Not fully deterministic. Review result carefully.",
  },
  unsupported: {
    label: "Unsupported",
    color: "#e57373",
    bg: "rgba(229,115,115,0.10)",
    border: "rgba(229,115,115,0.30)",
    description: "The requested operation is not within the current supported scope.",
  },
  ambiguous: {
    label: "Ambiguous",
    color: "#9e9e9e",
    bg: "rgba(158,158,158,0.10)",
    border: "rgba(158,158,158,0.30)",
    description: "Clarification required — cannot proceed without additional information.",
  },
};

function TrustBadge({ trustMetadata }) {
  if (!trustMetadata || typeof trustMetadata !== "object") {
    return null;
  }

  const trustClass = trustMetadata.trust_class;
  if (!trustClass || !TRUST_CONFIG[trustClass]) {
    return null;
  }

  const config = TRUST_CONFIG[trustClass];
  const coverageComplete = trustMetadata.operation_coverage_complete;
  const clarificationNeeded = trustMetadata.clarification_needed;
  const ambiguityReason = trustMetadata.ambiguity_reason;
  const unsupportedReason = trustMetadata.unsupported_reason;
  const advisoryDisclaimer = trustMetadata.advisory_disclaimer;
  const omittedOps = trustMetadata.omitted_operations || [];
  const warnings = trustMetadata.warnings || [];
  const limitations = trustMetadata.limitations || [];

  return (
    <div
      className="trust-badge"
      style={{
        display: "inline-flex",
        flexDirection: "column",
        gap: "4px",
        padding: "6px 10px",
        borderRadius: "5px",
        background: config.bg,
        border: `1px solid ${config.border}`,
        marginTop: "8px",
        marginBottom: "4px",
        fontSize: "13px",
        maxWidth: "100%",
      }}
    >
      {/* Trust class label */}
      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
        <span
          style={{
            fontWeight: 700,
            color: config.color,
            fontSize: "12px",
            letterSpacing: "0.04em",
            textTransform: "uppercase",
          }}
        >
          {config.label}
        </span>
        {coverageComplete === false && omittedOps.length > 0 && (
          <span
            style={{
              fontSize: "11px",
              color: "#e57373",
              marginLeft: "4px",
            }}
          >
            (incomplete coverage)
          </span>
        )}
      </div>

      {/* Description */}
      <div style={{ color: "#ccc", fontSize: "12px", lineHeight: 1.4 }}>
        {config.description}
      </div>

      {/* Ambiguity reason */}
      {clarificationNeeded && ambiguityReason && (
        <div style={{ color: "#aaa", fontSize: "12px", marginTop: "2px" }}>
          <strong>Reason:</strong> {ambiguityReason.replace(/_/g, " ")}
        </div>
      )}

      {/* Unsupported reason */}
      {trustClass === "unsupported" && unsupportedReason && (
        <div style={{ color: "#aaa", fontSize: "12px", marginTop: "2px" }}>
          <strong>Reason:</strong> {unsupportedReason.replace(/_/g, " ")}
        </div>
      )}

      {/* Advisory disclaimer */}
      {trustClass === "advisory" && advisoryDisclaimer && (
        <div
          style={{
            color: "#f5a623",
            fontSize: "11px",
            marginTop: "4px",
            fontStyle: "italic",
          }}
        >
          {advisoryDisclaimer}
        </div>
      )}

      {/* Omitted operations warning */}
      {omittedOps.length > 0 && (
        <div style={{ color: "#e57373", fontSize: "11px", marginTop: "2px" }}>
          Omitted operations: {omittedOps.join(", ")}
        </div>
      )}

      {/* Limitations */}
      {limitations.length > 0 && (
        <div style={{ color: "#aaa", fontSize: "11px", marginTop: "2px" }}>
          {limitations.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={{ color: "#f5a623", fontSize: "11px", marginTop: "2px" }}>
          {warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}
    </div>
  );
}

export default TrustBadge;
