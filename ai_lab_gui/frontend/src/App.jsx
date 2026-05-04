import { useState } from "react";
import ChatPanel from "./components/ChatPanel.jsx";
import WorkflowPanel from "./components/WorkflowPanel.jsx";
import ExecutionPanel from "./components/ExecutionPanel.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import BackgroundPanel from "./components/BackgroundPanel.jsx";
import ApprovalPanel from "./components/ApprovalPanel.jsx";
import "./styles.css";

export default function App() {
  const [lastResult, setLastResult] = useState(null);
  const [debugMode, setDebugMode] = useState(false);
  const [bgRefresh, setBgRefresh] = useState(0);

  function handleResult(result) {
    setLastResult(result);
  }

  function handleBackgroundStart() {
    setBgRefresh((n) => n + 1);
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
        <ChatPanel onResult={handleResult} />

        <div className="mid-row">
          <WorkflowPanel result={lastResult} />
          <ExecutionPanel result={lastResult} debugMode={debugMode} />
        </div>

        <ControlPanel onBackgroundStart={handleBackgroundStart} />

        <BackgroundPanel triggerRefresh={bgRefresh} />

        <ApprovalPanel />

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
