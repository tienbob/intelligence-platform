import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import RequireAuth from './components/RequireAuth';
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import Companies from './pages/Companies';
import CompanyDetail from './pages/CompanyDetail';
import News from './pages/News';
import NewsDetail from './pages/NewsDetail';
import Events from './pages/Events';
import EventDetail from './pages/EventDetail';
import Market from './pages/Market';
import Analysis from './pages/Analysis';
import AnalysisDetail from './pages/AnalysisDetail';
import Portfolio from './pages/Portfolio';
import Backtest from './pages/Backtest';
import Alerts from './pages/Alerts';
import Search from './pages/Search';
import Login from './pages/Login';
import Register from './pages/Register';

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
      <Route path="/portfolio" element={<Protected><Portfolio /></Protected>} />
      <Route path="/backtest" element={<Protected><Backtest /></Protected>} />
      <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
      <Route path="/search" element={<Protected><Search /></Protected>} />
    </Routes>
  );
}