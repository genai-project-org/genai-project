import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sparkles, ArrowLeft, ShieldCheck, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

/**
 * Two-step password recovery with a 6-digit OTP as the second factor:
 *   1. Enter email → server emails a code
 *   2. Enter the code → server returns a short-lived reset_token
 *   3. Enter new password → server updates the password and invalidates sessions
 *
 * We keep the whole flow inside a single screen so the user never has to jump
 * to a link in their inbox — that means email-based token theft can't work
 * even if the mailbox is compromised on another device.
 */
export default function ForgotPassword() {
  const [step, setStep] = useState('request'); // 'request' | 'verify' | 'reset' | 'done'
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const sendCode = async (e) => {
    e.preventDefault(); setLoading(true);
    try {
      await api.post('/auth/forgot-password', { email });
      toast.success('If your account exists, a code has been sent to your email');
      setStep('verify');
    } catch { toast.error('Could not send code'); }
    finally { setLoading(false); }
  };

  const verifyCode = async (e) => {
    e.preventDefault(); setLoading(true);
    try {
      const { data } = await api.post('/auth/verify-reset-otp', { email, otp });
      setResetToken(data.reset_token);
      setStep('reset');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Invalid or expired code');
    } finally { setLoading(false); }
  };

  const resetPassword = async (e) => {
    e.preventDefault(); setLoading(true);
    try {
      await api.post('/auth/reset-password', { token: resetToken, new_password: newPassword });
      setStep('done');
      toast.success('Password updated — signing you back in');
      setTimeout(() => navigate('/login'), 1500);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Could not update password');
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-background">
      <div className="w-full max-w-sm animate-fade-in-up">
        <Link to="/" className="flex items-center gap-2 mb-10">
          <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center">
            <Sparkles className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="font-display font-semibold">IEMA<span className="text-primary">.</span>ai</span>
        </Link>

        {step === 'request' && (
          <>
            <h1 className="font-display text-3xl font-medium tracking-tight">Forgot password?</h1>
            <p className="mt-2 text-sm text-muted-foreground">Enter your email &mdash; we&apos;ll send you a 6-digit code.</p>
            <form onSubmit={sendCode} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" data-testid="forgot-email-input" type="email"
                       value={email} onChange={(e) => setEmail(e.target.value)}
                       required placeholder="you@company.com" />
              </div>
              <Button type="submit" className="w-full" disabled={loading} data-testid="forgot-submit-btn">
                {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Send reset code
              </Button>
              <Link to="/login">
                <Button variant="ghost" size="sm" className="w-full mt-1">
                  <ArrowLeft className="h-4 w-4 mr-2" /> Back to sign in
                </Button>
              </Link>
            </form>
          </>
        )}

        {step === 'verify' && (
          <>
            <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center mb-6">
              <ShieldCheck className="h-6 w-6 text-primary" />
            </div>
            <h1 className="font-display text-2xl font-medium tracking-tight">Enter your code</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              We sent a 6-digit code to <span className="text-foreground">{email}</span>. It expires in 10 minutes.
            </p>
            <form onSubmit={verifyCode} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="otp">Verification code</Label>
                <Input id="otp" data-testid="forgot-otp-input" inputMode="numeric" maxLength={6}
                       value={otp}
                       onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                       required placeholder="123456"
                       className="tracking-[0.5em] text-center text-lg font-mono" />
              </div>
              <Button type="submit" className="w-full" disabled={loading || otp.length !== 6} data-testid="forgot-verify-btn">
                {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Verify code
              </Button>
              <Button variant="ghost" size="sm" className="w-full" type="button" onClick={() => setStep('request')}>
                Use a different email
              </Button>
            </form>
          </>
        )}

        {step === 'reset' && (
          <>
            <h1 className="font-display text-2xl font-medium tracking-tight">Choose a new password</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Any active sessions will be signed out after you save.
            </p>
            <form onSubmit={resetPassword} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="np">New password</Label>
                <Input id="np" data-testid="forgot-new-password" type="password" minLength={8}
                       value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                       required placeholder="Minimum 8 characters" />
              </div>
              <Button type="submit" className="w-full" disabled={loading || newPassword.length < 8}
                      data-testid="forgot-save-btn">
                {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Save new password
              </Button>
            </form>
          </>
        )}

        {step === 'done' && (
          <div className="text-center">
            <div className="h-14 w-14 rounded-2xl mx-auto bg-primary/10 border border-primary/30 flex items-center justify-center mb-6">
              <ShieldCheck className="h-6 w-6 text-primary" />
            </div>
            <h1 className="font-display text-2xl font-medium tracking-tight">Password updated</h1>
            <p className="mt-3 text-sm text-muted-foreground">Redirecting you to sign in…</p>
          </div>
        )}
      </div>
    </div>
  );
}
