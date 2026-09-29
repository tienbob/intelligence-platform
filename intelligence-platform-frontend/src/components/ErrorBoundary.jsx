import { Component } from 'react';

// Top-level render-fallback: a crash in any page (e.g. malformed API data)
// shows a friendly card instead of a white screen.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, errorInfo) {
    // Surface for debugging without breaking the UI.
    console.error('UI error caught by ErrorBoundary:', error, errorInfo);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex items-center justify-center min-h-screen p-6 bg-background">
          <div className="card max-w-md w-full text-center">
            <span className="material-symbols-outlined text-5xl mb-4 block text-error">error</span>
            <h1 className="text-2xl font-bold text-on-surface mb-2">Something went wrong</h1>
            <p className="text-sm text-on-surface-variant mb-6">
              An unexpected error occurred while rendering this page. Your data is safe — try again.
            </p>
            <div className="flex gap-2 justify-center">
              <button
                className="btn-secondary"
                onClick={() => this.setState({ error: null })}
              >
                Try again
              </button>
              <button
                className="btn-primary"
                onClick={() => { window.location.href = '/dashboard'; }}
              >
                Back to Dashboard
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
