import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import api from '@/lib/api';
import { setAuth } from '@/store/slices/authSlice';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sparkles, Loader2, Apple as AppleIcon, Github, Linkedin } from 'lucide-react';
import { AUTH } from '@/constants/testIds';

const GSI_SRC = 'https://accounts.google.com/gsi/client';
const APPLE_SRC = 'https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js';

export default function AuthPage({ mode }) {
  const isRegister = mode === 'register';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [oauthCfg, setOauthCfg] = useState({ google: {}, apple: {}, github: {}, linkedin: {} });
  const [searchParams] = useSearchParams();
  const googleBtnRef = useRef(null);
  const dispatch = useDispatch();
  const navigate = useNavigate();

  const handleAuthSuccess = (data, providerLabel) => {
    dispatch(setAuth(data));
    toast.success(`Signed in with ${providerLabel}`);
    navigate('/chat', { replace: true });
  };

  useEffect(() => {
    api.get('/auth/oauth-config').then((r) => setOauthCfg(r.data)).catch(() => {});
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    if (code && state) exchangeOAuthCode(state, code);
    // eslint-disable-next-line
  }, []);

  // Google Identity Services
  useEffect(() => {
    if (!oauthCfg.google?.enabled) return;
    const init = () => {
      if (!window.google?.accounts?.id) return;
      try {
        window.google.accounts.id.initialize({
          client_id: oauthCfg.google.client_id,
          callback: async (resp) => {
            if (!resp?.credential) { toast.error('Google did not return a credential'); return; }
            setLoading(true);
            try {
              const { data } = await api.post('/auth/google-verify', { credential: resp.credential });
              handleAuthSuccess(data, 'Google');
            } catch (err) {
              toast.error(err.response?.data?.detail || 'Google sign-in failed');
            } finally { setLoading(false); }
          },
          ux_mode: 'popup', auto_select: false, use_fedcm_for_prompt: true,
        });
        if (googleBtnRef.current) {
          window.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: 'outline', size: 'large',
            width: googleBtnRef.current.offsetWidth || 320,
            text: isRegister ? 'signup_with' : 'signin_with', shape: 'rectangular',
          });
        }
      } catch (e) { console.error('[Google] GIS init failed:', e); }
    };
    const existing = document.querySelector(`script[src="${GSI_SRC}"]`);
    if (existing) init();
    else {
      const s = document.createElement('script');
      s.src = GSI_SRC; s.async = true; s.defer = true; s.onload = init;
      document.body.appendChild(s);
    }
  }, [oauthCfg.google?.enabled, oauthCfg.google?.client_id, isRegister]);

  // Apple Sign-In JS
  useEffect(() => {
    if (!oauthCfg.apple?.enabled) return;
    const init = () => {
      if (!window.AppleID?.auth) return;
      try {
        window.AppleID.auth.init({
          clientId: oauthCfg.apple.client_id,
          scope: 'name email',
          redirectURI: window.location.origin + '/auth/callback',
          state: 'apple',
          usePopup: true,
        });
      } catch (e) { /* Apple init failed */ }
    };
    const existing = document.querySelector(`script[src="${APPLE_SRC}"]`);
    if (existing) init();
    else {
      const s = document.createElement('script');
      s.src = APPLE_SRC; s.async = true; s.defer = true; s.onload = init;
      document.body.appendChild(s);
    }
  }, [oauthCfg.apple?.enabled, oauthCfg.apple?.client_id]);

  const exchangeOAuthCode = async (provider, code) => {
    setLoading(true);
    try {
      const redirectUri = `${window.location.origin}/auth/callback`;
      const { data } = await api.post(`/auth/${provider}`, { code, redirect_uri: redirectUri });
      handleAuthSuccess(data, provider);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'OAuth failed');
      navigate('/login', { replace: true });
    } finally { setLoading(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const url = isRegister ? '/auth/register' : '/auth/login';
      const body = isRegister ? { email, password, name } : { email, password };
      const { data } = await api.post(url, body);
      dispatch(setAuth(data));
      toast.success(isRegister ? 'Account created — enjoy your 100 welcome credits!' : 'Welcome back');
      navigate('/chat');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Something went wrong');
    } finally { setLoading(false); }
  };

  const githubSignIn = () => {
    if (!oauthCfg.github?.enabled) { toast.info('GitHub OAuth not configured'); return; }
    const redirect_uri = window.location.origin + '/auth/callback';
    const url = 'https://github.com/login/oauth/authorize?' + new URLSearchParams({
      client_id: oauthCfg.github.client_id, redirect_uri, scope: 'read:user user:email', state: 'github',
    }).toString();
    window.location.href = url;
  };

  const linkedinSignIn = () => {
    if (!oauthCfg.linkedin?.enabled) { toast.info('LinkedIn OAuth not configured'); return; }
    const redirect_uri = window.location.origin + '/auth/callback';
    const url = 'https://www.linkedin.com/oauth/v2/authorization?' + new URLSearchParams({
      response_type: 'code', client_id: oauthCfg.linkedin.client_id, redirect_uri,
      scope: 'openid profile email', state: 'linkedin',
    }).toString();
    window.location.href = url;
  };

  const appleSignIn = async () => {
    if (!oauthCfg.apple?.enabled) { toast.info('Apple Sign-In not configured'); return; }
    if (!window.AppleID?.auth) { toast.error('Apple SDK not loaded yet, try again'); return; }
    setLoading(true);
    try {
      const resp = await window.AppleID.auth.signIn();
      const idToken = resp?.authorization?.id_token;
      if (!idToken) throw new Error('No id_token from Apple');
      const { data } = await api.post('/auth/apple', { id_token: idToken });
      handleAuthSuccess(data, 'Apple');
    } catch (err) {
      if (err?.error === 'popup_closed_by_user' || err?.error === 'user_cancelled_authorize') return;
      toast.error(err?.response?.data?.detail || err?.error || err?.message || 'Apple sign-in failed');
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen flex bg-background">
      <div className="hidden lg:flex flex-col justify-between w-1/2 relative overflow-hidden bg-[hsl(var(--surface))] border-r border-border p-10">
        <div className="grid-pattern absolute inset-0 opacity-40" />
        <Link to="/" className="relative flex items-center gap-2">
          <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center">
            <Sparkles className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="font-display font-semibold">supercreator<span className="text-primary">.</span>ai</span>
        </Link>
        <div className="relative max-w-md">
          <div className="text-xs uppercase tracking-wider text-primary mb-3">v2.0</div>
          <h2 className="font-display text-3xl font-medium tracking-tight leading-tight">One AI to learn, build a career, and grow.</h2>
          <p className="mt-3 text-muted-foreground">12 intelligence modules — chat, career, resume, interviews, courses and more — with one credit wallet across web + mobile.</p>
          <div className="mt-8 grid grid-cols-3 gap-4 text-sm">
            <div><div className="font-display text-2xl font-medium">100</div><div className="text-xs text-muted-foreground">Welcome credits</div></div>
            <div><div className="font-display text-2xl font-medium">20</div><div className="text-xs text-muted-foreground">Daily free credits</div></div>
            <div><div className="font-display text-2xl font-medium">12</div><div className="text-xs text-muted-foreground">Modules</div></div>
          </div>
        </div>
        <div className="relative text-xs text-muted-foreground">&copy; 2026 supercreator.ai — Own the data. Grow every day.</div>
      </div>

      <div className="flex-1 flex flex-col justify-center items-center p-6">
        <div className="w-full max-w-sm animate-fade-in-up">
          <Link to="/" className="lg:hidden flex items-center gap-2 mb-8">
            <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center"><Sparkles className="h-4 w-4 text-primary-foreground" /></div>
            <span className="font-display font-semibold">supercreator<span className="text-primary">.</span>ai</span>
          </Link>
          <h1 className="font-display text-3xl font-medium tracking-tight">{isRegister ? 'Create your account' : 'Welcome back'}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {isRegister ? 'Start with 100 credits. No card required.' : 'Sign in to continue to your workspace.'}
          </p>

          <div className="mt-6 space-y-2">
            <div ref={googleBtnRef} data-testid={AUTH.googleBtn} className="w-full flex justify-center min-h-[44px]">
              {!oauthCfg.google?.enabled && <Button variant="outline" className="w-full justify-center" disabled>Google (not configured)</Button>}
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Button variant="outline" size="sm" onClick={appleSignIn} disabled={!oauthCfg.apple?.enabled || loading} data-testid="auth-apple-btn">
                <AppleIcon className="h-4 w-4 mr-1" /> Apple
              </Button>
              <Button variant="outline" size="sm" onClick={githubSignIn} disabled={!oauthCfg.github?.enabled || loading} data-testid="auth-github-btn">
                <Github className="h-3.5 w-3.5 mr-1" /> GitHub
              </Button>
              <Button variant="outline" size="sm" onClick={linkedinSignIn} disabled={!oauthCfg.linkedin?.enabled || loading} data-testid="auth-linkedin-btn">
                <Linkedin className="h-3.5 w-3.5 mr-1 text-[#0a66c2]" /> LinkedIn
              </Button>
            </div>
          </div>

          <div className="my-6 flex items-center gap-3 text-xs text-muted-foreground">
            <div className="h-px flex-1 bg-border" /><span>or continue with email</span><div className="h-px flex-1 bg-border" />
          </div>

          <form onSubmit={submit} className="space-y-3">
            {isRegister && (
              <div className="space-y-1.5">
                <Label htmlFor="name">Full name</Label>
                <Input id="name" data-testid={AUTH.nameInput} value={name} onChange={(e) => setName(e.target.value)} required placeholder="Jane Doe" />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" data-testid={AUTH.emailInput} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@company.com" />
            </div>
            <div className="space-y-1.5 relative">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                {!isRegister && (
                  <Link to="/forgot-password" className="text-xs text-muted-foreground hover:text-primary" data-testid="auth-forgot-link">Forgot?</Link>
                )}
              </div>
              <Input id="password" data-testid={AUTH.passwordInput} type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} placeholder="••••••••" />
            </div>
            <Button type="submit" className="w-full" disabled={loading} data-testid={AUTH.submitBtn}>
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {isRegister ? 'Create account' : 'Sign in'}
            </Button>
          </form>

          <div className="mt-6 text-center text-sm text-muted-foreground">
            {isRegister ? (
              <>Already have an account? <Link to="/login" data-testid={AUTH.toggleLink} className="text-primary hover:underline">Sign in</Link></>
            ) : (
              <>New here? <Link to="/register" data-testid={AUTH.toggleLink} className="text-primary hover:underline">Create an account</Link></>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
