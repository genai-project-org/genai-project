import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { PublicClientApplication } from '@azure/msal-browser';
import { toast } from 'sonner';
import api from '@/lib/api';
import { setAuth } from '@/store/slices/authSlice';

// Global MSAL handler — mounts once, catches Microsoft redirect responses on any route
export default function MsalRedirectHandler() {
  const dispatch = useDispatch();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data: cfg } = await api.get('/auth/oauth-config');
        if (!cfg?.microsoft?.enabled || !cfg.microsoft?.client_id) return;
        if (cancelled) return;
        const pending = (() => { try { return sessionStorage.getItem('iema_msal_pending'); } catch { return null; } })();
        const hasHashCode = !!(window.location.hash && (
          window.location.hash.includes('code=') ||
          window.location.hash.includes('id_token=') ||
          window.location.hash.includes('access_token=') ||
          window.location.hash.includes('error=')
        ));
        if (!pending && !hasHashCode) return; // No pending redirect to handle
        const msal = new PublicClientApplication({
          auth: {
            clientId: cfg.microsoft.client_id,
            authority: 'https://login.microsoftonline.com/common',
            redirectUri: window.location.origin,
          },
          cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
        });
        await msal.initialize();
        const result = await msal.handleRedirectPromise();
        try { sessionStorage.removeItem('iema_msal_pending'); } catch { /* ignore */ }
        if (result?.idToken) {
          const { data } = await api.post('/auth/microsoft-verify', { id_token: result.idToken });
          dispatch(setAuth(data));
          toast.success('Signed in with Microsoft');
          navigate('/chat', { replace: true });
        }
      } catch (err) {
        console.error('[MS] global redirect handler error:', err);
        try { sessionStorage.removeItem('iema_msal_pending'); } catch { /* ignore */ }
        // Only surface errors if we actually initiated a Microsoft sign-in
        const msg = err?.errorMessage || err?.response?.data?.detail || err?.message;
        if (msg) toast.error('Microsoft: ' + msg);
      }
    })();
    return () => { cancelled = true; };
  }, [dispatch, navigate]);

  return null;
}
