import { Navigate, Outlet } from 'react-router-dom';
import { useSelector } from 'react-redux';

// A lightweight auth-only layout for routes that must render WITHOUT the
// Sidebar/topbar (the live Mock Interview session and its report) — mirrors
// AppLayout.jsx's `if (!access_token) return <Navigate to="/login" replace />`
// gate, but skips rendering any chrome around the <Outlet />. Kept separate
// from AppLayout rather than teaching it to special-case a path, since that
// would mean threading a "chromeless" flag through every route definition.
export default function ChromelessGuard() {
  const { access_token } = useSelector((s) => s.auth);
  if (!access_token) return <Navigate to="/login" replace />;
  return <Outlet />;
}
