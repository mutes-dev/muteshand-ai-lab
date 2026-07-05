/**
 * DOCUMENT STAGING PANEL — SPRINT-11-SLICE-006-FIX1
 *
 * Polished GUI document staging surface with styled dropzone and drag/drop.
 * - Hidden native file input behind styled button/label.
 * - Bounded drag-and-drop for one file at a time.
 * - Stages file via backend endpoint.
 * - Shows staged metadata.
 * - Action buttons insert ordinary prompt text into parent input.
 *
 * Per GUI_FUNCTIONALITY_CONTRACT_V2:
 * - Frontend is projection-only and non-authoritative.
 * - Does NOT parse, preview, OCR, or index files.
 * - Does NOT create a document library or manager.
 */

import { useState, useRef, useCallback } from "react";
import { api } from "../api.js";

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

export default function DocumentStagingPanel({ onInsertPrompt }) {
  const [staged, setStaged] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef(null);
  const dragCounterRef = useRef(0);
  // Prevents the click event that sometimes fires after a drop from opening the file picker
  const justDroppedRef = useRef(false);

  async function stageFile(file) {
    if (!file) return;

    setError(null);
    setUploading(true);
    setStaged(null);

    try {
      const result = await api.stageDocument(file);
      if (result.status === "success" && result.staged_path) {
        setStaged(result);
      } else {
        setError(result.message || "Staging failed");
      }
    } catch (err) {
      setError(err.message || "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function handleFileSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    stageFile(file);
  }

  function triggerFileInput() {
    if (justDroppedRef.current) {
      return;
    }
    if (!uploading && fileInputRef.current) {
      fileInputRef.current.click();
    }
  }

  const handleDragEnter = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      setIsDragOver(false);
      dragCounterRef.current = 0;
    }
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();

    // Suppress the click event that browsers sometimes fire immediately after a drop
    justDroppedRef.current = true;
    window.setTimeout(() => {
      justDroppedRef.current = false;
    }, 200);

    dragCounterRef.current = 0;
    setIsDragOver(false);

    if (uploading) return;

    const dt = e.dataTransfer;
    console.log("[STAGING:DROP] dataTransfer", {
      types: dt?.types,
      filesLength: dt?.files?.length,
      itemsLength: dt?.items?.length,
    });

    let file = null;

    // Primary: dataTransfer.files (standard HTML5)
    if (dt?.files && dt.files.length > 0) {
      if (dt.files.length > 1) {
        setError("Please stage one file at a time.");
        return;
      }
      file = dt.files[0];
      console.log("[STAGING:DROP] file from dataTransfer.files", {
        name: file.name,
        size: file.size,
        type: file.type,
      });
    }

    // Fallback: dataTransfer.items (WebView / older browser compat)
    if (!file && dt?.items) {
      const fileItems = Array.from(dt.items).filter((it) => it.kind === "file");
      if (fileItems.length > 1) {
        setError("Please stage one file at a time.");
        return;
      }
      if (fileItems.length === 1) {
        file = fileItems[0].getAsFile();
        console.log("[STAGING:DROP] file from dataTransfer.items", {
          name: file?.name,
          size: file?.size,
          type: file?.type,
        });
      }
    }

    if (!file) {
      // Detect if the drop carried non-file content (e.g., text, URL)
      const hasStringItems = dt?.items
        ? Array.from(dt.items).some((it) => it.kind === "string")
        : false;
      if (hasStringItems) {
        setError("Dropped content is not a file. Please drop a local file or use the Select file button.");
      } else {
        setError("No file detected. This browser or WebView may not support drag-and-drop file access. Please use the Select file button.");
      }
      return;
    }

    // WebView2 on Windows sometimes reports file size 0 for dropped files
    // because the File object is a stub without actual content access.
    if (file.size === 0 && !file.type) {
      console.warn("[STAGING:DROP] File appears empty (size=0, type=\"\"). WebView may not support drag-and-drop file access.");
      setError("Dropped file appears unreadable. This browser or WebView may not support drag-and-drop file access. Please use the Select file button.");
      return;
    }

    stageFile(file);
  }, [uploading]);

  function insertPrompt(action) {
    if (!staged?.staged_path) return;
    const path = staged.staged_path;
    let prompt = "";
    switch (action) {
      case "read":
        prompt = `Read the file "${path}"`;
        break;
      case "summarize":
        prompt = `Summarize the file "${path}"`;
        break;
      case "extract":
        prompt = `Extract key points from the file "${path}"`;
        break;
      case "explain":
        prompt = `Explain the file "${path}"`;
        break;
      case "question":
        prompt = `Answer this question from "${path}": `;
        break;
      default:
        return;
    }
    if (onInsertPrompt) {
      onInsertPrompt(prompt);
    }
  }

  const dropzoneLabel = uploading
    ? "Staging file…"
    : isDragOver
      ? "Drop file here"
      : "Drop a document here or select file";

  return (
    <div className="document-staging-panel">
      {/* Styled dropzone */}
      <div
        className={`staging-dropzone${isDragOver ? " drag-over" : ""}${uploading ? " uploading" : ""}`}
        onClick={triggerFileInput}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        aria-label="Document staging dropzone"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            triggerFileInput();
          }
        }}
      >
        <div className="staging-dropzone__content">
          <span className="staging-dropzone__icon" aria-hidden="true">
            {uploading ? "⟳" : isDragOver ? "↓" : "📄"}
          </span>
          <span className="staging-dropzone__label">{dropzoneLabel}</span>
          <button
            className="btn-secondary"
            onClick={(e) => {
              e.stopPropagation();
              triggerFileInput();
            }}
            disabled={uploading}
            type="button"
          >
            Select file
          </button>
          <span className="staging-dropzone__hint">
            PDF, DOCX, CSV, XLSX, images, text, or other local files
          </span>
        </div>
      </div>

      {/* Hidden native file input */}
      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileSelect}
        disabled={uploading}
        style={{ display: "none" }}
      />

      {/* Error */}
      {error && <div className="staging-error">{error}</div>}

      {/* Staged metadata card */}
      {staged && (
        <div className="staging-card">
          <div className="staging-card__meta">
            <strong>{staged.filename}</strong>
            <span>{formatBytes(staged.size_bytes)}</span>
            <span className="staging-type">{staged.detected_type}</span>
          </div>
          <div className="staging-card__path">{staged.staged_path}</div>
          <div className="btn-group">
            <button
              className="btn-control"
              onClick={() => insertPrompt("read")}
              title="Insert: Read the file"
            >
              Read
            </button>
            <button
              className="btn-control"
              onClick={() => insertPrompt("summarize")}
              title="Insert: Summarize the file"
            >
              Summarize
            </button>
            <button
              className="btn-control"
              onClick={() => insertPrompt("extract")}
              title="Insert: Extract key points"
            >
              Extract key points
            </button>
            <button
              className="btn-control"
              onClick={() => insertPrompt("explain")}
              title="Insert: Explain the file"
            >
              Explain
            </button>
            <button
              className="btn-control"
              onClick={() => insertPrompt("question")}
              title="Insert: Answer this question from the file"
            >
              Question
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
