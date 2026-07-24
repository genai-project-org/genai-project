import { useState } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sparkles, Loader2, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    if (password !== confirm) { toast.error('Passwords do not match'); return; }
    if (password.length < 6) { toast.error('Password must be 6+ chars'); return; }
    setLoading(true);
    try {
      await api.post('/auth/reset-password', { token, new_password: password });
      setDone(true);
      setTimeout(() => navigate('/login'), 2000);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to reset password');
    } finally { setLoading(false); }
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <p className="text-muted-foreground">Invalid reset link.</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-background">
      <div className="w-full max-w-sm animate-fade-in-up">
        <Link to="/" className="flex items-center gap-2 mb-10">
          <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center">
            <Sparkles className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="font-display font-semibold">supercreator<span className="text-primary">.</span>ai</span>
        </Link>
        {done ? (
          <div className="text-center">
            <div className="h-14 w-14 rounded-2xl mx-auto bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center mb-6">
              <CheckCircle2 className="h-6 w-6 text-emerald-400" />
            </div>
            <h1 className="font-display text-2xl font-medium tracking-tight">Password updated</h1>
            <p className="mt-3 text-sm text-muted-foreground">Redirecting to sign in…</p>
          </div>
        ) : (
          <>
            <h1 className="font-display text-3xl font-medium tracking-tight">Set a new password</h1>
            <p className="mt-2 text-sm text-muted-foreground">Choose a strong password you haven't used before.</p>
            <form onSubmit={submit} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="pw">New password</Label>
                <Input id="pw" data-testid="reset-password-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="confirm">Confirm password</Label>
                <Input id="confirm" data-testid="reset-confirm-input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={6} />
              </div>
              <Button type="submit" className="w-full" disabled={loading} data-testid="reset-submit-btn">
                {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Reset password
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
