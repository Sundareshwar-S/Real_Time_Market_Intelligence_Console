import { Component } from "react";

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-card">
            <span className="material-symbols-outlined error-icon">error</span>
            <h2>Something went wrong</h2>
            <p>{this.state.error?.message || "An unexpected error occurred."}</p>
            <button
              type="button"
              className="action-btn"
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
            >
              Reload Application
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function LoadingOverlay({ visible }) {
  if (!visible) {
    return null;
  }
  return (
    <div className="loading-overlay">
      <div className="loading-spinner" />
      <p>Initializing data streams...</p>
    </div>
  );
}
