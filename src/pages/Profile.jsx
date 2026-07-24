import { useState, useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { setUser } from '@/store/slices/authSlice';
import { Badge } from '@/components/ui/badge';
import { MailCheck, Mail, Loader2, ShieldCheck } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';

export default function Profile() {
  const user = useSelector((s) => s.auth.user);
  const [name, setName] = useState(user?.name || '');
  const [saving, setSaving] = useState(false);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [code, setCode] = useState('');
  const dispatch = useDispatch();

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.patch('/auth/me', { name });
      dispatch(setUser(data));
      toast.success('Profile updated');
    } catch (e) {
      toast.error('Failed to update');
    } finally { setSaving(false); }
  };

  const sendVerify = async () => {
    setSending(true);
    try {
      await api.post('/auth/send-verify-email');
      toast.success('Verification code sent to ' + user.email);
      setVerifyOpen(true);
    } catch (e) {
      toast.error('Failed to send code');
    } finally { setSending(false); }
  };

  const verify = async () => {
    setVerifying(true);
    try {
      await api.post('/auth/verify-email', { code });
      const { data } = await api.get('/auth/me');
      dispatch(setUser(data));
      toast.success('Email verified!');
      setVerifyOpen(false);
      setCode('');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Invalid code');
    } finally { setVerifying(false); }
  };

  return (
    <div className="p-6 md:p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-medium tracking-tight">Profile</h1>
        <p className="text-muted-foreground mt-1">Your public account information.</p>
      </div>

      {!user?.email_verified && (
        <div className="mb-6 rounded-xl border border-primary/30 bg-primary/5 p-4 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <Mail className="h-5 w-5 text-primary" />
            <div>
              <div className="font-medium">Verify your email</div>
              <div className="text-sm text-muted-foreground">We'll send a 6-digit code to {user?.email}</div>
            </div>
          </div>
          <Button size="sm" onClick={sendVerify} disabled={sending} data-testid="verify-email-btn">
            {sending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Send code
          </Button>
        </div>
      )}

      <div className="rounded-xl border border-border bg-card p-6 mb-6">
        <div className="flex items-center gap-4 mb-6">
          <div className="h-16 w-16 rounded-full bg-primary/15 flex items-center justify-center text-primary text-2xl font-semibold">
            {(user?.name || '?').charAt(0).toUpperCase()}
          </div>
          <div>
            <div className="font-display text-xl font-medium">{user?.name}</div>
            <div className="text-sm text-muted-foreground flex items-center gap-1.5">
              {user?.email}
              {user?.email_verified && <MailCheck className="h-3.5 w-3.5 text-emerald-400" />}
            </div>
            <div className="flex gap-2 mt-1">
              <Badge variant="secondary" className="text-xs">{user?.role}</Badge>
              <Badge variant="outline" className="text-xs">via {user?.provider}</Badge>
              {user?.email_verified && <Badge variant="outline" className="text-xs text-emerald-400 border-emerald-400/30"><ShieldCheck className="h-3 w-3 mr-1" />verified</Badge>}
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">Full name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Email</Label>
            <Input value={user?.email} disabled />
          </div>
          <Button onClick={save} disabled={saving}>Save changes</Button>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-6">
        <h3 className="font-display text-lg font-medium mb-4">Connected accounts</h3>
        <div className="space-y-2">
          {[
            { p: 'Google', enabled: user?.provider === 'google' },
            { p: 'Microsoft', enabled: user?.provider === 'microsoft' },
            { p: 'Apple', enabled: false },
            { p: 'Facebook', enabled: false },
          ].map(({ p, enabled }) => (
            <div key={p} className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
              <span className="text-sm">{p}</span>
              {enabled
                ? <Badge variant="outline" className="text-xs text-emerald-400 border-emerald-400/30">Connected</Badge>
                : <Badge variant="outline" className="text-xs">Not connected</Badge>}
            </div>
          ))}
        </div>
      </div>

      <Dialog open={verifyOpen} onOpenChange={setVerifyOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Verify your email</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Enter the 6-digit code we sent to <span className="text-foreground">{user?.email}</span>.</p>
            <Input
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="000000"
              className="text-center font-mono text-2xl tracking-[0.5em]"
              maxLength={6}
              data-testid="verify-code-input"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setVerifyOpen(false)}>Cancel</Button>
            <Button onClick={verify} disabled={code.length !== 6 || verifying} data-testid="verify-submit-btn">
              {verifying && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Verify
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
