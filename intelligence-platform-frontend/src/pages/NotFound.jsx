import { Link } from 'react-router-dom';

// Catch-all route (audit U06): unknown URLs previously rendered a blank
// page because no route matched.
export default function NotFound() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div className="card max-w-md w-full text-center">
        <span className="material-symbols-outlined text-5xl mb-4 block text-primary">search_off</span>
        <h1 className="text-2xl font-bold text-on-surface mb-2">Page not found</h1>
        <p className="text-sm text-on-surface-variant mb-6">
          The page you're looking for doesn't exist or may have moved.
        </p>
        <div className="flex gap-2 justify-center">
          <Link to="/" className="btn-secondary">Home</Link>
          <Link to="/dashboard" className="btn-primary">Back to Dashboard</Link>
        </div>
      </div>
    </div>
  );
}