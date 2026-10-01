import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import PageTitle from './components/PageTitle';
import RequireAuth from './components/RequireAuth';

// Route-level code splitting: each page becomes its own chunk, loaded on
// demand, instead of one ~750 kB bundle on first paint.
const Landing = lazy(() => import('./pages/Landing'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Companies = lazy(() => import('./pages/Companies'));
const CompanyDetail = lazy(() => import('./pages/CompanyDetail'));
const News = lazy(() => import('./pages/News'));
const NewsDetail = lazy(() => import('./pages/NewsDetail'));
const Events = lazy(() => import('./pages/Events'));
const EventDetail = lazy(() => import('./pages/EventDetail'));
const Market = lazy(() => import('./pages/Market'));
const Analysis = lazy(() => import('./pages/Analysis'));
const AnalysisDetail = lazy(() => import('./pages/AnalysisDetail'));
const Opportunities = lazy(() => import('./pages/Opportunities'));
const Backtest = lazy(() => import('./pages/Backtest'));
const Alerts = lazy(() => import('./pages/Alerts'));
const Search = lazy(() => import('./pages/Search'));
const Login = lazy(() => import('./pages/Login'));
const Register = lazy(() => import('./pages/Register'));
const NotFound = lazy(() => import('./pages/NotFound'));

function PageFallback() {
  return (
    <div role="status" className="flex items-center justify-center py-32">
      <div className="text-on-surface-variant text-lg">Loading…</div>
    </div>
  );
}

// Wraps a protected route in auth guard + app layout.
function Protected({ children }) {
  return (
    <RequireAuth>
      <Layout>{children}</Layout>
    </RequireAuth>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <PageTitle />
      <Routes>
        {/* Public landing page */}
        <Route path="/" element={<Landing />} />

        {/* Public auth pages */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        {/* Protected app pages (require login) */}
        <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
        <Route path="/companies" element={<Protected><Companies /></Protected>} />
        <Route path="/companies/:ticker" element={<Protected><CompanyDetail /></Protected>} />
        <Route path="/news" element={<Protected><News /></Protected>} />
        <Route path="/news/:id" element={<Protected><NewsDetail /></Protected>} />
        <Route path="/events" element={<Protected><Events /></Protected>} />
        <Route path="/events/:id" element={<Protected><EventDetail /></Protected>} />
        <Route path="/market" element={<Protected><Market /></Protected>} />
        <Route path="/analysis" element={<Protected><Analysis /></Protected>} />
        <Route path="/analysis/:analysisId" element={<Protected><AnalysisDetail /></Protected>} />
        <Route path="/opportunities" element={<Protected><Opportunities /></Protected>} />
        <Route path="/portfolio" element={<Navigate to="/opportunities" replace />} />
        <Route path="/backtest" element={<Protected><Backtest /></Protected>} />
        <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
        <Route path="/search" element={<Protected><Search /></Protected>} />

        {/* Unknown URLs get a real page instead of a blank render (audit U06) */}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}