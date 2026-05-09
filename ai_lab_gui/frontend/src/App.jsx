import { useState, useEffect, useRef } from "react";
import ChatPanel from "./components/ChatPanel.jsx";
import WorkflowPanel from "./components/WorkflowPanel.jsx";
import ExecutionPanel from "./components/ExecutionPanel.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import BackgroundPanel from "./components/BackgroundPanel.jsx";
import ApprovalPanel from "./components/ApprovalPanel.jsx";
import { waitForBackend, api } from "./api.js";
import { log } from "./utils/log.js";
import "./styles.css";

const STREAM_POLL_MS = 500;

export default function App() {
  const [lastResult, setLastResult] = useState(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [activeWorkflowId, setActiveWorkflowId] = useState(null);
  const [debugMode, setDebugMode] = useState(false);
  const [bgRefresh, setBgRefresh] = useState(0);
  const [backendReady, setBackendReady] = useState(false);
  const [backendError, setBackendError] = useState(null);
  const streamPollRef = useRef(null);
  const activeWorkflowIdRef = useRef(null);

  useEffect(() => {
    waitForBackend(20, 500)
      .then(() => setBackendReady(true))
      .catch((e) => setBackendError(e.message));
  }, []);

  // === DEFAULT WORKFLOW HANDLING (Phase 4B.2) ===
  // Per GUI_FUNCTIONALITY_CONTRACT_V1: MUST track active workflow_id
  // Fallback to first available workflow if active one is deleted/missing
  useEffect(() => {
    if (!backendReady) return;

    const checkAndFallback = async () => {
      try {
        const res = await api.backgroundList();
        const workflows = res.workflows ?? [];

        if (workflows.length === 0) {
          // No workflows available - keep current active (might be from new execution)
          return;
        }

        const workflowIds = workflows.map(wf => wf.workflow_id);

        // Check if active workflow still exists
        if (activeWorkflowIdRef.current && !workflowIds.includes(activeWorkflowIdRef.current)) {
          // Active workflow is missing - fallback to first available
          const fallbackId = workflowIds[0];
          log("WORKFLOW_FALLBACK", {
            missing: activeWorkflowIdRef.current,
            fallback: fallbackId
          });
          setActiveWorkflowId(fallbackId);
          activeWorkflowIdRef.current = fallbackId;
        }

        // If no active workflow set but workflows exist, set first as default
        if (!activeWorkflowIdRef.current && workflowIds.length > 0) {
          const defaultId = workflowIds[0];
          log("WORKFLOW_DEFAULT_SET", { workflow_id: defaultId });
          setActiveWorkflowId(defaultId);
          activeWorkflowIdRef.current = defaultId;
        }
      } catch (_) {
        // Silent fail - don't disrupt UI on check failure
      }
    };

    // Check immediately and then periodically
    checkAndFallback();
    const interval = setInterval(checkAndFallback, 5000);
    return () => clearInterval(interval);
  }, [backendReady, bgRefresh]);

  function stopStreamPoll() {
    if (streamPollRef.current) {
      clearInterval(streamPollRef.current);
      streamPollRef.current = null;
    }
  }

  function handleExecutionStart() {
    setIsExecuting(true);
    setActiveWorkflowId(null);
    activeWorkflowIdRef.current = null;
    setLastResult(null);
    log("EXECUTION_START", { activeWorkflowId: null });
  }

  function handleStreamStart(bgId) {
    stopStreamPoll();
    streamPollRef.current = setInterval(async () => {
      try {
        const wfData = await api.streamWorkflowId(bgId);
        console.log("AUDIT_STREAM_RESPONSE:", wfData);
        console.log("AUDIT_STREAM_RESULT:", wfData.result);
        console.log("AUDIT_STREAM_OUTPUTS_LENGTH:", wfData.result?.outputs?.length);
        if (wfData.workflow_id && wfData.workflow_id !== activeWorkflowIdRef.current) {
          activeWorkflowIdRef.current = wfData.workflow_id;
          setActiveWorkflowId(wfData.workflow_id);
        }
        if (wfData.result) {
          setLastResult(wfData.result);
        }
        if (wfData.status === "COMPLETED" || wfData.status === "FAILED") {
          stopStreamPoll();
          if (wfData.status === "FAILED") {
            setLastResult({ status: "failure", reason: wfData.error || "Unknown error" });
          }
          setIsExecuting(false);
        }
      } catch (_) {
        // poll silently
      }
    }, STREAM_POLL_MS);
  }

  function handleResult(result) {
    log("RESULT_UPDATE", { result_status: result?.status, result_payload: result, result_workflow_id: result?.workflow_id });
    setLastResult(result);
    log("SET_LAST_RESULT", { status: result?.status, source: "handle_result" });
    setIsExecuting(false);
  }

  function handleBackgroundStart() {
    setBgRefresh((n) => n + 1);
  }

  function handleResumeStreamStart(bgId) {
    log("RESUME_STREAM_START", { bgId });
    setIsExecuting(true);
    handleStreamStart(bgId);
  }

  if (backendError) {
    return (
      <div className="app">
        <header className="app-header">
          <span className="logo">⬡ AI Lab</span>
        </header>
        <main className="layout">
          <div className="startup-error">
            <h2>⚠ Backend Unavailable</h2>
            <p>{backendError}</p>
            <p className="muted">
              Ensure Python and uvicorn are installed, then restart the application.
            </p>
            <button
              className="btn-primary"
              onClick={() => {
                setBackendError(null);
                setBackendReady(false);
                waitForBackend(20, 500)
                  .then(() => setBackendReady(true))
                  .catch((e) => setBackendError(e.message));
              }}
            >
              Retry
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (!backendReady) {
    return (
      <div className="app">
        <header className="app-header">
          <span className="logo">⬡ AI Lab</span>
        </header>
        <main className="layout">
          <div className="startup-loading">
            <div className="spinner" />
            <p>Starting backend…</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">⬡ AI Lab</span>
        <label className="debug-toggle">
          <input
            type="checkbox"
            checked={debugMode}
            onChange={(e) => setDebugMode(e.target.checked)}
          />
          Debug Mode
        </label>
      </header>

      <main className="layout">
        <ChatPanel
          onResult={handleResult}
          onExecutionStart={handleExecutionStart}
          onStreamStart={handleStreamStart}
          isExecuting={isExecuting}
          activeWorkflowId={activeWorkflowId}
        />

        <div className="mid-row">
          <WorkflowPanel
            result={lastResult}
            isExecuting={isExecuting}
            activeWorkflowId={activeWorkflowId}
          />
          <ExecutionPanel result={lastResult} debugMode={debugMode} />
        </div>

        <ControlPanel
          onBackgroundStart={handleBackgroundStart}
          onResumeStreamStart={handleResumeStreamStart}
          workflowId={activeWorkflowId}
        />

        <BackgroundPanel
          triggerRefresh={bgRefresh}
          activeWorkflowId={activeWorkflowId}
          onSelectWorkflow={setActiveWorkflowId}
        />

        <ApprovalPanel workflowId={activeWorkflowId} />

        {debugMode && lastResult && (
          <section className="panel debug-panel">
            <h2>Raw Workflow JSON</h2>
            <pre className="json-dump">{JSON.stringify(lastResult, null, 2)}</pre>
          </section>
        )}
      </main>
    </div>
  );
}
