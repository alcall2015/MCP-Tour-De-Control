import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Catches a render error so one bad panel never blanks the whole page. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught an error", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="card p-4 space-y-2">
        <h3 className="text-sm font-semibold" style={{ fontFamily: "'Space Grotesk', system-ui, sans-serif", color: "var(--text-primary)" }}>
          Something went wrong on this page
        </h3>
        <pre className="text-xs whitespace-pre-wrap" style={{ color: "var(--error)" }}>{error.message}</pre>
        <button type="button" className="btn-secondary btn-sm" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
