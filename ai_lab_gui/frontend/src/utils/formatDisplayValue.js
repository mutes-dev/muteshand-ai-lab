/**
 * Frontend-safe formatter for unknown result values
 * Prevents crashes when rendering objects, null, or undefined values
 */

/**
 * Extract a deterministic presentation string from a successful structured
 * execution result, without altering execution truth.
 *
 * Rules (per F5A generic presentation convention):
 * - execution_result.status must be "success".
 * - execution_result.result must be a plain object.
 * - Prefer result.display_text, fall back to result.answer_text.
 * - Field must be a non-empty string with non-whitespace content.
 *
 * Returns null if the rule does not apply, preserving existing display behavior.
 */
export function getStructuredPresentationText(executionResult) {
  if (!executionResult || typeof executionResult !== "object") return null;
  if (executionResult.status !== "success") return null;

  const result = executionResult.result;
  if (!result || Object.prototype.toString.call(result) !== "[object Object]") {
    return null;
  }

  const candidate = result.display_text ?? result.answer_text;
  if (typeof candidate !== "string") return null;
  if (candidate.trim().length === 0) return null;

  return candidate;
}

export function formatDisplayValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/**
 * Format a value for display with optional truncation
 */
export function formatDisplayValueTruncated(value, maxLength = 40) {
  const formatted = formatDisplayValue(value);
  if (formatted.length <= maxLength) return formatted;
  return formatted.slice(0, maxLength) + "...";
}

/**
 * Compact preview for dense UI lists.
 * - Trims leading/trailing whitespace
 * - Takes first few non-empty lines
 * - Caps each line and total length
 * - Returns full formatted string if already short
 */
export function formatDisplayValueCompact(
  value,
  maxLines = 3,
  maxCharsPerLine = 80,
  totalMaxChars = 120,
) {
  const formatted = formatDisplayValue(value).trim();
  if (formatted.length <= totalMaxChars) {
    return formatted;
  }
  const lines = formatted.split("\n").filter((line) => line.trim() !== "");
  const preview = lines
    .slice(0, maxLines)
    .map((line) => (line.length > maxCharsPerLine ? line.slice(0, maxCharsPerLine) + "..." : line))
    .join(" / ");
  if (preview.length > totalMaxChars) {
    return preview.slice(0, totalMaxChars) + "...";
  }
  return preview || formatted.slice(0, totalMaxChars) + "...";
}

/**
 * Check if a value can be safely used with string methods
 */
export function isStringLike(value) {
  return typeof value === "string";
}
