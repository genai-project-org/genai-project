import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import api from '@/lib/api';
import { Sparkles, Loader2 } from 'lucide-react';

/**
 * Mobile OAuth Bridge — reached by the mobile app via
 * `WebBrowser.openAuthSessionAsync(webOrigin + '/mobile-oauth?provider=…&app_scheme=iemaai')`.
 *
 * GitHub and LinkedIn refuse to register a custom-scheme redirect URI
 * (`iemaai://…`), so we do the whole OAuth dance here on the (already-
 * registered) web origin, then push the resulting JWTs back to the app
 * via the deep-link scheme.
 *
 * Flow:
 *   1.  Mobile app opens this page with `?provider=github&app_scheme=iemaai`.
 *   2.  We hit `/api/auth/oauth-config`, then redirect the browser to the
 *       provider's authorize URL using **this exact page** as the
 *       `redirect_uri`. That URI is what the OAuth app registered.
 *   3.  Provider bounces back to this page with `?code=…&state=…`.
 *   4.  We POST `/api/auth/{provider}` to exchange the code, receive
 *       `{ user, tokens }`, then `window.location = "iemaai://auth?…"`
 *       to hand them back to the app.
 */
export default function MobileOAuthBridge() {
  const [params] = useSearchParams();
  const provider = params.get('provider') || '';
  const appScheme = params.get('app_scheme') || 'iemaai';
  const code = params.get('code');
  const stateRet = params.get('state');
  const err = params.get('error') || params.get('error_description');
  const [msg, setMsg] = useState('Preparing sign-in…');
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const backToApp = (search) => {
      window.location.replace(`${appScheme}://auth?${search}`);
    };

    if (err) {
      setMsg(`Sign-in failed: ${err}`);
      setTimeout(() => backToApp(`error=${encodeURIComponent(err)}`), 800);
      return;
    }

    // Callback leg — provider redirected back with `?code=` + our state.
    if (code && stateRet && stateRet.startsWith('mobile:')) {
      const [, prov] = stateRet.split(':');
      (async () => {
        setMsg('Signing you in…');
        try {
          const redirectUri = window.location.origin + window.location.pathname;
          const { data } = await api.post(`/auth/${prov}`, { code, redirect_uri: redirectUri });
          const search = new URLSearchParams({
            access_token: data.tokens.access_token,
            refresh_token: data.tokens.refresh_token,
            user: JSON.stringify(data.user),
          }).toString();
          backToApp(search);
        } catch (e) {
          const detail = e.response?.data?.detail || e.message || 'OAuth failed';
          setMsg(detail);
          setTimeout(() => backToApp(`error=${encodeURIComponent(detail)}`), 1500);
        }
      })();
      return;
    }

    // Start leg — bounce the user to the provider.
    (async () => {
      try {
        const { data: cfg } = await api.get('/auth/oauth-config');
        if (!cfg?.[provider]?.enabled) throw new Error(`${provider} not configured`);
        const redirectUri = window.location.origin + window.location.pathname;
        const state = `mobile:${provider}:${Math.random().toString(36).slice(2)}`;
        let authUrl;
        if (provider === 'github') {
          authUrl = 'https://github.com/login/oauth/authorize?' + new URLSearchParams({
            client_id: cfg.github.client_id,
            redirect_uri: redirectUri,
            scope: 'read:user user:email',
            state,
          }).toString();
        } else if (provider === 'linkedin') {
          authUrl = 'https://www.linkedin.com/oauth/v2/authorization?' + new URLSearchParams({
            response_type: 'code',
            client_id: cfg.linkedin.client_id,
            redirect_uri: redirectUri,
            scope: 'openid profile email',
            state,
          }).toString();
        } else if (provider === 'google') {
          authUrl = 'https://accounts.google.com/o/oauth2/v2/auth?' + new URLSearchParams({
            client_id: cfg.google.client_id,
            redirect_uri: redirectUri,
            response_type: 'code',
            scope: 'openid email profile',
            state,
          }).toString();
        } else {
          throw new Error(`Unsupported provider: ${provider}`);
        }
        window.location.replace(authUrl);
      } catch (e) {
        const detail = e.message || 'Could not start sign-in';
        setMsg(detail);
        setTimeout(() => backToApp(`error=${encodeURIComponent(detail)}`), 1500);
      }
    })();
    // eslint-disable-next-line
  }, []);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-background text-center">
      <div className="flex items-center gap-2 mb-8">
        <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center">
          <Sparkles className="h-4 w-4 text-primary-foreground" />
        </div>
        <span className="font-display font-semibold">supercreator<span className="text-primary">.</span>ai</span>
      </div>
      <Loader2 className="h-6 w-6 animate-spin text-primary mb-4" />
      <p className="text-sm text-muted-foreground max-w-sm">{msg}</p>
      <p className="text-xs text-muted-foreground mt-8">Provider: <span className="font-mono">{provider}</span></p>
    </div>
  );
}
