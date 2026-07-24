import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Provider } from 'react-redux';
import { store } from '@/store/store';
import ThemeProvider from '@/context/ThemeProvider';
import { Toaster } from 'sonner';

import Landing from '@/pages/Landing';
import AuthPage from '@/pages/AuthPage';
import AuthCallback from '@/pages/AuthCallback';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';
import MobileOAuthBridge from '@/pages/MobileOAuthBridge';
import AppLayout from '@/components/AppLayout';
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
import Builder from '@/pages/Builder';
import Counseling from '@/pages/Counseling';

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
            <Route path="/payment-success" element={<PaymentSuccess />} />

            <Route element={<AppLayout />}>
              <Route path="/chat" element={<Chat />} />
              <Route path="/studio" element={<Studio />} />
              <Route path="/career" element={<Career />} />
              <Route path="/builder" element={<Builder />} />
              <Route path="/counseling" element={<Counseling />} />
              <Route path="/usage" element={<Usage />} />
              <Route path="/wallet" element={<Wallet />} />
              <Route path="/billing" element={<Billing />} />
              <Route path="/notifications" element={<Notifications />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/admin" element={<Admin />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </Provider>
  );
}

export default App;
