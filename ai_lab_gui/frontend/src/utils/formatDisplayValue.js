/**
 * Frontend-safe formatter for unknown result values
 * Prevents crashes when rendering objects, null, or undefined values
 */

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
 * Check if a value can be safely used with string methods
 */
export function isStringLike(value) {
  return typeof value === "string";
}
