import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    // Log the error to console
    console.error("[REACT_ERROR_BOUNDARY]", {
      error: error.message,
      stack: error.stack,
      componentStack: errorInfo.componentStack,
      timestamp: new Date().toISOString(),
    });

    // Store error details for display
    this.setState({
      error: error,
      errorInfo: errorInfo,
    });
  }

  handleReload = () => {
    window.location.reload();
  };

  handleDismiss = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: "20px",
          margin: "20px",
          border: "1px solid #ff6b6b",
          borderRadius: "8px",
          backgroundColor: "#ffe0e0",
          color: "#d63031",
          fontFamily: "monospace",
          fontSize: "14px",
          lineHeight: "1.5",
        }}>
          <h2 style={{ margin: "0 0 10px 0", color: "#d63031" }}>
            ⚠️ Frontend Render Error
          </h2>
          <p style={{ margin: "0 0 15px 0" }}>
            The application encountered a rendering error and could not display the current view.
          </p>
          
          <details style={{ marginBottom: "15px" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold" }}>
              Error Details (click to expand)
            </summary>
            <div style={{ 
              marginTop: "10px", 
              padding: "10px", 
              backgroundColor: "#fff", 
              border: "1px solid #ddd",
              borderRadius: "4px",
              fontSize: "12px",
              overflow: "auto",
              maxHeight: "200px"
            }}>
              <div><strong>Error:</strong> {this.state.error?.message}</div>
              {this.state.error?.stack && (
                <div style={{ marginTop: "10px" }}>
                  <strong>Stack:</strong>
                  <pre style={{ margin: "5px 0", whiteSpace: "pre-wrap" }}>
                    {this.state.error.stack}
                  </pre>
                </div>
              )}
              {this.state.errorInfo?.componentStack && (
                <div style={{ marginTop: "10px" }}>
                  <strong>Component Stack:</strong>
                  <pre style={{ margin: "5px 0", whiteSpace: "pre-wrap" }}>
                    {this.state.errorInfo.componentStack}
                  </pre>
                </div>
              )}
            </div>
          </details>

          <div style={{ display: "flex", gap: "10px" }}>
            <button 
              onClick={this.handleReload}
              style={{
                padding: "8px 16px",
                backgroundColor: "#d63031",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Reload App
            </button>
            <button 
              onClick={this.handleDismiss}
              style={{
                padding: "8px 16px",
                backgroundColor: "#74b9ff",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Try to Continue
            </button>
          </div>
          
          <p style={{ 
            margin: "15px 0 0 0", 
            fontSize: "12px", 
            color: "#666",
            fontStyle: "italic"
          }}>
            Check the browser console for additional details. This error has been logged automatically.
          </p>
        </div>
      );
    }

    return this.props.children;
  }
}
