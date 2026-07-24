import { useEffect, useRef, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { useDispatch } from 'react-redux';
import { setAuth } from '@/store/slices/authSlice';
import { toast } from 'sonner';
import { Loader2, Sparkles } from 'lucide-react';

/**
 * OAuth callback — shared by web AND mobile.
 *
 *  - Web flow: state is the plain provider name (`github`, `linkedin`, `google`).
 *    We exchange the code, hydrate Redux, and navigate to `/chat`.
 *  - Mobile flow: state is `mobile:<provider>:<nonce>`. We exchange the code
 *    on the backend, then `window.location.replace('iemaai://auth?…')` so
 *    the deep link hands the JWTs back to the Expo app.
 *
 * Using the same callback URL for both means each OAuth provider only needs
 * a single registered redirect URI, which is what GitHub (and every other
 * strict provider) mandates.
 */
export default function AuthCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('Signing you in…');
  const exchangedRef = useRef(false);

  useEffect(() => {
    // Guard against React StrictMode double-invocation which would replay
    // the single-use OAuth code and cause the second exchange to fail.
    if (exchangedRef.current) return;
    exchangedRef.current = true;

    const code = params.get('code');
    const rawState = params.get('state') || '';
    const err = params.get('error');
    if (err) { setError(err); toast.error(`OAuth error: ${err}`); setTimeout(() => navigate('/login'), 2000); return; }
    if (!code || !rawState) { navigate('/login', { replace: true }); return; }

    const isMobile = rawState.startsWith('mobile:');
    const appScheme = isMobile ? (rawState.split(':')[2] || 'iemaai') : null;
    const provider = isMobile ? rawState.split(':')[1] : rawState;

    (async () => {
      try {
        const redirectUri = `${window.location.origin}/auth/callback`;
        const { data } = await api.post(`/auth/${provider}`, { code, redirect_uri: redirectUri });
        if (isMobile) {
          // Hand tokens back to the Expo app via the deep-link scheme.
          setStatus('Returning to the app…');
          const search = new URLSearchParams({
            access_token: data.tokens.access_token,
            refresh_token: data.tokens.refresh_token,
            user: JSON.stringify(data.user || {}),
          }).toString();
          window.location.replace(`${appScheme}://auth?${search}`);
          return;
        }
        dispatch(setAuth(data));
        toast.success(`Signed in with ${provider}`);
        navigate('/chat', { replace: true });
      } catch (e) {
        const detail = e.response?.data?.detail || e.message || 'OAuth failed';
        setError(detail);
        toast.error(detail);
        if (isMobile) {
          setTimeout(() => window.location.replace(`${appScheme}://auth?error=${encodeURIComponent(detail)}`), 1200);
        } else {
          setTimeout(() => navigate('/login'), 2000);
        }
      }
    })();
    // eslint-disable-next-line
  }, []);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background">
      <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center mb-6">
        <Sparkles className="h-6 w-6 text-primary" />
      </div>
      {!error ? (
        <>
          <Loader2 className="h-6 w-6 animate-spin text-primary mb-2" />
          <p className="text-muted-foreground">{status}</p>
        </>
      ) : (
        <p className="text-destructive text-sm">{error}</p>
      )}
    </div>
  );
}
