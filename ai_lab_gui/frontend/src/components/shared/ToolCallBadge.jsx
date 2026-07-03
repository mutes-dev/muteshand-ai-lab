/**
 * TOOL CALL BADGE — FOUNDATION-RETOUCH-002-AI1
 *
 * Compact display-only badge for tool-call metadata.
 * Shows human-readable tool label and category.
 *
 * Authority: PROJECTION_CONTINUITY_CONTRACT_V1, GUI_ARCHITECTURE.txt
 *
 * RULES:
 * - Purely presentational — NO authority logic
 * - NO lifecycle inference — receives all data as props
 * - Absent-safe: missing data renders nothing or fallback
 */

import { getToolDisplayMetadata } from "../../constants/toolDisplayMetadata.js";

/**
 * ToolCallBadge — compact tool metadata display
 *
 * @param {Object} props
 * @param {string} props.toolName — raw tool name (e.g. "read_file")
 * @param {string} [props.fallbackLabel] — optional fallback if metadata missing
 * @param {string} [props.size="small"] — badge size: "small" | "medium"
 */
export default function ToolCallBadge({ toolName, fallbackLabel, size = "small" }) {
  if (!toolName || typeof toolName !== "string") {
    return null;
  }

  const meta = getToolDisplayMetadata(toolName);
  const label = meta.label || fallbackLabel || toolName;
  const color = meta.color || "#94a3b8";

  const fontSize = size === "small" ? "0.75rem" : "0.875rem";
  const padding = size === "small" ? "1px 6px" : "2px 8px";

  return (
    <span
      className="tool-call-badge"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        fontSize,
        padding,
        borderRadius: "4px",
        background: `${color}18`,
        color,
        border: `1px solid ${color}44`,
        fontWeight: 500,
        lineHeight: 1.4,
        whiteSpace: "nowrap",
      }}
      title={`Tool: ${toolName}`}
    >
      <span className="tool-call-badge__prefix" style={{ opacity: 0.7 }}>
        Tool:
      </span>
      <span className="tool-call-badge__label">{label}</span>
    </span>
  );
}
