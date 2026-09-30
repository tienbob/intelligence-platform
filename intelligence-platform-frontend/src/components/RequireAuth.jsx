import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../services/auth';

// Redirects to /login if the user is not authenticated.
export default function RequireAuth({ children }) {
  const { isAuthenticated, loading, error, retrySession } = useAuth();
  const location = useLocation();

  if (loading) return <p role="status" className="p-6">Checking your session…</p>;
  if (error) return <div role="alert" className="card m-6"><p>{error}</p><button className="btn-secondary mt-3" onClick={retrySession}>Retry</button></div>;
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search + location.hash }} />;
  }
  return children;
}