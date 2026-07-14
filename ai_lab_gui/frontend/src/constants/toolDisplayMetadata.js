/**
 * TOOL DISPLAY METADATA — FOUNDATION-RETOUCH-002-AI1-FIX1
 *
 * CANONICAL SOURCE:
 * system/tool_index/tools.json ui_display is the canonical tool display metadata source.
 * This frontend file is a temporary static mirror for display-only GUI badges.
 * When a production tool's ui_display label/category changes in tools.json,
 * update this file in the same change.
 *
 * The Python drift test tests/internal/tool_index/test_frontend_tool_display_mirror.py
 * enforces parity between this mirror and tools.json.
 *
 * RULES:
 * - Purely presentational — NO authority logic
 * - Absent-safe: missing tools fall back to raw tool name
 * - Display-only: does NOT affect execution, lifecycle, governance
 * - Static mirror: must be kept in sync with backend tools.json ui_display
 */

const _TOOL_DISPLAY_MAP = {
  add_numbers: { label: "Add numbers", category: "math" },
  cube_number: { label: "Cube number", category: "math" },
  divide_numbers: { label: "Divide numbers", category: "math" },
  factorial: { label: "Factorial", category: "math" },
  fibonacci: { label: "Fibonacci", category: "math" },
  list_files: { label: "List files", category: "read" },
  multiply_numbers: { label: "Multiply numbers", category: "math" },
  multiply_string: { label: "Repeat string", category: "string" },
  read_csv: { label: "Read CSV", category: "read" },
  read_file: { label: "Read file", category: "read" },
  read_image_text: { label: "Read image text", category: "read" },
  read_pdf: { label: "Read PDF", category: "read" },
  read_pdf_ocr: { label: "Read PDF OCR", category: "read" },
  read_docx: { label: "Read DOCX", category: "read" },
  read_spreadsheet: { label: "Read Spreadsheet", category: "read" },
  preview_table_schema: { label: "Preview table schema", category: "read" },
  resolve_table_reference: { label: "Resolve table reference", category: "read" },
  analyze_table: { label: "Analyze table", category: "analysis" },
  read_webpage: { label: "Read webpage", category: "web" },
  square_number: { label: "Square number", category: "math" },
  square_root: { label: "Square root", category: "math" },
  subtract_numbers: { label: "Subtract numbers", category: "math" },
  web_search: { label: "Search web", category: "search" },
  finalize_output: { label: "Finalize output", category: "synthesis" },
  semantic_transform: { label: "Semantic transform", category: "synthesis" },
  write_file: { label: "Write file", category: "write" },
  grep: { label: "Search file", category: "search" },
  glob: { label: "Find files", category: "search" },
  append_file: { label: "Append file", category: "write" },
  edit_file: { label: "Edit file", category: "write" },
};

const _CATEGORY_COLOR = {
  read: "#3b82f6",
  write: "#f97316",
  search: "#8b5cf6",
  web: "#06b6d4",
  math: "#22c55e",
  string: "#ec4899",
  system: "#64748b",
  synthesis: "#a855f7",
  analysis: "#f59e0b",
  unknown: "#94a3b8",
};

/**
 * Get display metadata for a tool name.
 * Falls back to raw tool name and "unknown" category if not found.
 */
export function getToolDisplayMetadata(toolName) {
  if (!toolName || typeof toolName !== "string") {
    return { label: null, category: "unknown", color: _CATEGORY_COLOR.unknown };
  }
  const meta = _TOOL_DISPLAY_MAP[toolName];
  if (meta) {
    return {
      label: meta.label,
      category: meta.category,
      color: _CATEGORY_COLOR[meta.category] || _CATEGORY_COLOR.unknown,
    };
  }
  return {
    label: toolName,
    category: "unknown",
    color: _CATEGORY_COLOR.unknown,
  };
}

/**
 * Get human-readable label for a tool name.
 */
export function getToolLabel(toolName) {
  return getToolDisplayMetadata(toolName).label;
}

/**
 * Get display category for a tool name.
 */
export function getToolCategory(toolName) {
  return getToolDisplayMetadata(toolName).category;
}

/**
 * Get display color for a tool category.
 */
export function getToolCategoryColor(category) {
  return _CATEGORY_COLOR[category] || _CATEGORY_COLOR.unknown;
}
