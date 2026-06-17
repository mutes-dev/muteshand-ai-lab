import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";

// Global error instrumentation for debugging
window.addEventListener("error", (event) => {
  console.error("[GLOBAL_FRONTEND_ERROR]", {
    message: event.message,
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
    error: event.error?.stack || String(event.error),
    timestamp: new Date().toISOString(),
  });
});

window.addEventListener("unhandledrejection", (event) => {
  console.error("[GLOBAL_FRONTEND_UNHANDLED_REJECTION]", {
    reason: event.reason?.stack || String(event.reason),
    timestamp: new Date().toISOString(),
  });
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
