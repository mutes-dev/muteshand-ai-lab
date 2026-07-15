/**
 * RowSetTable — Generic dynamic row-set presentation component.
 *
 * Renders a structured row-set payload returned by analyze_table (filter,
 * and future F5B-2 operations: sort, top_n, bottom_n, rank).
 *
 * SHAPE DETECTION — renders only when:
 *   executionResult.status === "success"
 *   AND result is a plain object
 *   AND result.rows is a non-empty array
 *   AND rows[0].cells is a non-empty array
 *   AND cells[0] has column_index and a "value" key
 *
 * AUTHORITY BOUNDARY:
 *   - All data is rendered as received from the backend. No rows are added,
 *     removed, sorted, filtered, or recomputed in the frontend.
 *   - Pagination is presentation-only and does not alter backend ordering.
 *   - Backend truncation (result_complete / truncated) is reported separately
 *     from frontend pagination. They are never conflated.
 */

import { useState, useMemo } from "react";

const PAGE_SIZE = 25;
const CELL_PREVIEW_MAX = 120;

function _isRowSet(result) {
  if (!result || typeof result !== "object") return false;
  if (!Array.isArray(result.rows) || result.rows.length === 0) return false;
  const first = result.rows[0];
  if (!first || !Array.isArray(first.cells) || first.cells.length === 0) return false;
  const firstCell = first.cells[0];
  if (typeof firstCell !== "object" || firstCell === null) return false;
  if (typeof firstCell.column_index === "undefined") return false;
  if (!("value" in firstCell)) return false;
  return true;
}

function _deriveColumns(rows) {
  const colMap = new Map();
  for (const row of rows) {
    if (!Array.isArray(row.cells)) continue;
    for (const cell of row.cells) {
      const idx = cell.column_index;
      if (typeof idx === "number" && !colMap.has(idx)) {
        colMap.set(idx, cell.column_name ?? "");
      }
    }
  }
  return Array.from(colMap.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([column_index, column_name]) => ({ column_index, column_name }));
}

function _cellDisplayValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  const s = String(value);
  return s;
}

function _truncatePreview(s) {
  if (s.length <= CELL_PREVIEW_MAX) return { preview: s, truncated: false };
  return { preview: s.slice(0, CELL_PREVIEW_MAX) + "…", truncated: true };
}

function Cell({ value }) {
  const raw = _cellDisplayValue(value);
  const { preview, truncated } = _truncatePreview(raw);
  if (truncated) {
    return (
      <td
        style={tdStyle}
        title={raw}
        aria-label={raw}
      >
        <span style={{ cursor: "help" }}>{preview}</span>
      </td>
    );
  }
  return <td style={tdStyle}>{preview}</td>;
}

const thStyle = {
  padding: "6px 10px",
  textAlign: "left",
  fontWeight: 600,
  fontSize: "12px",
  color: "#bbb",
  borderBottom: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(0,0,0,0.25)",
  whiteSpace: "nowrap",
  position: "sticky",
  top: 0,
  zIndex: 1,
};

const tdStyle = {
  padding: "5px 10px",
  fontSize: "13px",
  color: "#e0e0e0",
  borderBottom: "1px solid rgba(255,255,255,0.06)",
  maxWidth: "320px",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const sourceColStyle = {
  ...tdStyle,
  color: "#888",
  fontSize: "12px",
  fontVariantNumeric: "tabular-nums",
};

const sourceHeaderStyle = {
  ...thStyle,
  color: "#888",
};

function PaginationControls({ page, totalPages, rowCount, returnedCount, onPrev, onNext }) {
  if (totalPages <= 1) return null;
  const start = page * PAGE_SIZE + 1;
  const end = Math.min((page + 1) * PAGE_SIZE, returnedCount);
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: "10px",
      fontSize: "12px",
      color: "#aaa",
      marginTop: "6px",
      flexWrap: "wrap",
    }}>
      <button
        onClick={onPrev}
        disabled={page === 0}
        style={{
          padding: "3px 10px",
          background: "rgba(255,255,255,0.07)",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "3px",
          color: page === 0 ? "#555" : "#ccc",
          cursor: page === 0 ? "default" : "pointer",
          fontSize: "12px",
        }}
      >
        ‹ Prev
      </button>
      <span>
        Page {page + 1} of {totalPages} — displaying rows {start}–{end} of {returnedCount} returned rows
      </span>
      <button
        onClick={onNext}
        disabled={page === totalPages - 1}
        style={{
          padding: "3px 10px",
          background: "rgba(255,255,255,0.07)",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "3px",
          color: page === totalPages - 1 ? "#555" : "#ccc",
          cursor: page === totalPages - 1 ? "default" : "pointer",
          fontSize: "12px",
        }}
      >
        Next ›
      </button>
    </div>
  );
}

export default function RowSetTable({ result }) {
  const [page, setPage] = useState(0);

  const isRowSet = useMemo(() => _isRowSet(result), [result]);

  const columns = useMemo(() => {
    if (!isRowSet) return [];
    return _deriveColumns(result.rows);
  }, [isRowSet, result]);

  if (!isRowSet || columns.length === 0) return null;

  const rows = result.rows;
  const returnedRowCount = typeof result.returned_row_count === "number"
    ? result.returned_row_count
    : rows.length;
  const matchedRowCount = typeof result.matched_row_count === "number"
    ? result.matched_row_count
    : returnedRowCount;
  const resultComplete = result.result_complete !== false && result.truncated !== true;
  const backendTruncated = !resultComplete;

  const warnings = Array.isArray(result.warnings) ? result.warnings : [];
  const limitations = Array.isArray(result.limitations) ? result.limitations : [];

  const totalPages = Math.ceil(returnedRowCount / PAGE_SIZE);
  const safePage = Math.min(page, Math.max(0, totalPages - 1));
  const pageRows = rows.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  function handlePrev() { setPage(p => Math.max(0, p - 1)); }
  function handleNext() { setPage(p => Math.min(totalPages - 1, p + 1)); }

  return (
    <div style={{ marginTop: "12px" }}>

      {/* Result count / status strip */}
      <div style={{ fontSize: "13px", color: "#aaa", marginBottom: "6px" }}>
        {backendTruncated ? (
          <span style={{ color: "#f5a623" }}>
            Showing {returnedRowCount.toLocaleString()} of {matchedRowCount.toLocaleString()} matching rows. The backend result is truncated.
          </span>
        ) : returnedRowCount === 1 ? (
          <span>1 matching row returned.</span>
        ) : (
          <span>{returnedRowCount.toLocaleString()} matching rows returned.</span>
        )}
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={{ marginBottom: "6px" }}>
          {warnings.map((w, i) => (
            <div key={i} style={{ fontSize: "12px", color: "#f5a623", padding: "2px 0" }}>{w}</div>
          ))}
        </div>
      )}

      {/* Limitations */}
      {limitations.length > 0 && (
        <div style={{ marginBottom: "6px" }}>
          {limitations.map((l, i) => (
            <div key={i} style={{ fontSize: "12px", color: "#aaa", padding: "2px 0" }}>{l}</div>
          ))}
        </div>
      )}

      {/* Table */}
      <div style={{
        overflowX: "auto",
        overflowY: "auto",
        maxHeight: "400px",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: "4px",
        background: "rgba(0,0,0,0.15)",
      }}>
        <table style={{
          borderCollapse: "collapse",
          width: "100%",
          fontSize: "13px",
        }}>
          <thead>
            <tr>
              <th style={sourceHeaderStyle}>Source row</th>
              {columns.map(col => (
                <th
                  key={`col-${col.column_index}`}
                  style={thStyle}
                >
                  {col.column_name && col.column_name.trim()
                    ? col.column_name
                    : `Column ${col.column_index}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, rowIdx) => {
              const cellByIdx = {};
              if (Array.isArray(row.cells)) {
                for (const cell of row.cells) {
                  cellByIdx[cell.column_index] = cell.value;
                }
              }
              const sourceRef = row.row_number ?? row.row_ref ?? (safePage * PAGE_SIZE + rowIdx + 1);
              return (
                <tr key={`row-${safePage}-${rowIdx}`} style={{ background: rowIdx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.02)" }}>
                  <td style={sourceColStyle}>{sourceRef}</td>
                  {columns.map(col => (
                    <Cell
                      key={`row-${safePage}-${rowIdx}-col-${col.column_index}`}
                      value={cellByIdx.hasOwnProperty(col.column_index) ? cellByIdx[col.column_index] : undefined}
                    />
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <PaginationControls
        page={safePage}
        totalPages={totalPages}
        rowCount={matchedRowCount}
        returnedCount={returnedRowCount}
        onPrev={handlePrev}
        onNext={handleNext}
      />
    </div>
  );
}
