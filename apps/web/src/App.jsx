import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Provider } from 'react-redux';
import { store } from '@/store/store';
import ThemeProvider from '@/context/ThemeProvider';
import { Toaster } from 'sonner';

import Landing from '@/pages/Landing';
import AuthPage from '@/pages/AuthPage';
import AuthCallback from '@/pages/AuthCallback';
import ForgotPassword from '@/pages/ForgotPassword';
import Privacy from '@/pages/Privacy';
import ResetPassword from '@/pages/ResetPassword';
import MobileOAuthBridge from '@/pages/MobileOAuthBridge';
import AppLayout from '@/components/AppLayout';
import ChromelessGuard from '@/components/ChromelessGuard';
import MsalRedirectHandler from '@/components/MsalRedirectHandler';
import Chat from '@/pages/Chat';
import Usage from '@/pages/Usage';
import Wallet from '@/pages/Wallet';
import Billing from '@/pages/Billing';
import PaymentSuccess from '@/pages/PaymentSuccess';
import Notifications from '@/pages/Notifications';
import Profile from '@/pages/Profile';
import Settings from '@/pages/Settings';
import Admin from '@/pages/Admin';
import Studio from '@/pages/Studio';
import Career from '@/pages/Career';
import Connectors from '@/pages/Connectors';
import ConnectorOAuthCallback from '@/pages/ConnectorOAuthCallback';
import Builder from '@/pages/Builder';
import Counseling from '@/pages/Counseling';
import Resume from '@/pages/Resume';
import Practice from '@/pages/Practice';
import Roadmap from '@/pages/Roadmap';
import Contest from '@/pages/Contest';
import InterviewHome from '@/pages/interview/InterviewHome';
import InterviewSetup from '@/pages/interview/InterviewSetup';
import InterviewSession from '@/pages/interview/InterviewSession';
import InterviewReport from '@/pages/interview/InterviewReport';

function App() {
  return (
    <Provider store={store}>
      <ThemeProvider>
        <BrowserRouter>
          <Toaster position="top-right" richColors />
          {/* Microsoft OAuth removed */}
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route path="/register" element={<AuthPage mode="register" />} />
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/mobile-oauth" element={<MobileOAuthBridge />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="/payment-success" element={<PaymentSuccess />} />
            <Route path="/connectors/oauth-callback" element={<ConnectorOAuthCallback />} />

            <Route element={<AppLayout />}>
              <Route path="/chat" element={<Chat />} />
              <Route path="/studio" element={<Studio />} />
              <Route path="/career" element={<Career />} />
              <Route path="/connectors" element={<Connectors />} />
              <Route path="/resume" element={<Resume />} />
              <Route path="/builder" element={<Builder kind="static" />} />
              <Route path="/builder/dynamic" element={<Builder kind="react" />} />
              <Route path="/practice" element={<Practice />} />
              <Route path="/roadmap" element={<Roadmap />} />
              <Route path="/contest" element={<Contest />} />
              <Route path="/interview" element={<InterviewHome />} />
              <Route path="/interview/new" element={<InterviewSetup />} />
              <Route path="/counseling" element={<Counseling />} />
              <Route path="/usage" element={<Usage />} />
              <Route path="/wallet" element={<Wallet />} />
              <Route path="/billing" element={<Billing />} />
              <Route path="/notifications" element={<Notifications />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/admin" element={<Admin />} />
            </Route>

            {/* Live Mock Interview session + its report render WITHOUT the
                Sidebar/topbar (a fullscreen, proctored, distraction-free
                surface) — a separate auth-guarded route group instead of
                teaching AppLayout to special-case a path. */}
            <Route element={<ChromelessGuard />}>
              <Route path="/interview/:sessionId" element={<InterviewSession />} />
              <Route path="/interview/:sessionId/report" element={<InterviewReport />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </Provider>
  );
}

export default App;
