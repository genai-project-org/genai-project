import { useEffect, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog';
import { Sparkles, Zap, Cpu } from 'lucide-react';
import { toast } from 'sonner';
import { setTheme } from '@/store/slices/uiSlice';
import { logout, setAuth } from '@/store/slices/authSlice';
import { cn } from '@/lib/utils';

const AI_PROVIDERS = [
  { key: 'iema',   label: 'supercreator (recommended)', Icon: Sparkles, desc: 'Data lake first, then randomly picks Claude or OpenAI. Best value.' },
  { key: 'claude', label: 'Claude',              Icon: Cpu,      desc: 'Always use Anthropic Claude Haiku 4.5.' },
  { key: 'openai', label: 'OpenAI',              Icon: Zap,      desc: 'Always use OpenAI GPT-4o mini.' },
];

export default function Settings() {
  const theme = useSelector((s) => s.ui.theme);
  const user = useSelector((s) => s.auth.user);
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const [confirmText, setConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [provider, setProvider] = useState(user?.ai_provider || 'iema');
  const [savingProv, setSavingProv] = useState(false);

  useEffect(() => { setProvider(user?.ai_provider || 'iema'); }, [user]);

  const saveProvider = async (p) => {
    if (p === provider) return;
    setProvider(p); setSavingProv(true);
    try {
      const { data } = await api.patch('/auth/me', { ai_provider: p });
      dispatch(setAuth({ user: data }));
      toast.success('AI preference saved');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed');
    } finally { setSavingProv(false); }
  };

  const deleteAccount = async () => {
    if (confirmText !== 'DELETE') return;
    setDeleting(true);
    try {
      await api.delete('/auth/me');
      toast.success('Account permanently deleted');
      dispatch(logout());
      navigate('/');
    } catch (e) {
      toast.error('Failed to delete account');
    } finally { setDeleting(false); }
  };

  return (
    <div className="p-6 md:p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-medium tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1">Manage preferences and account.</p>
      </div>

      <div className="rounded-xl border border-border bg-card p-6 mb-6" data-testid="settings-ai-provider">
        <h3 className="font-display text-lg font-medium mb-1">AI provider</h3>
        <p className="text-sm text-muted-foreground mb-4">Choose which model powers your AI experiences.</p>
        <div className="space-y-2">
          {AI_PROVIDERS.map((p) => (
            <button key={p.key} onClick={() => saveProvider(p.key)} disabled={savingProv}
              data-testid={`settings-provider-${p.key}`}
              className={cn(
                'w-full text-left flex items-start gap-3 p-3 rounded-lg border transition-all',
                provider === p.key ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40'
              )}>
              <div className={cn('h-8 w-8 rounded-md flex-shrink-0 flex items-center justify-center',
                provider === p.key ? 'bg-primary/15' : 'bg-[hsl(var(--surface))]')}>
                <p.Icon className={cn('h-4 w-4', provider === p.key ? 'text-primary' : 'text-muted-foreground')} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{p.label}</div>
                <div className="text-xs text-muted-foreground mt-0.5">{p.desc}</div>
              </div>
              {provider === p.key && <span className="text-xs text-primary uppercase tracking-wider">Active</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-6 mb-6">
        <h3 className="font-display text-lg font-medium mb-4">Appearance</h3>
        <RadioGroup value={theme} onValueChange={(v) => dispatch(setTheme(v))}>
          {['light', 'dark', 'system'].map((t) => (
            <div key={t} className="flex items-center gap-3">
              <RadioGroupItem value={t} id={`theme-${t}`} />
              <Label htmlFor={`theme-${t}`} className="capitalize cursor-pointer">{t}</Label>
            </div>
          ))}
        </RadioGroup>
      </div>

      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6">
        <h3 className="font-display text-lg font-medium mb-2 text-destructive">Danger zone</h3>
        <p className="text-sm text-muted-foreground mb-4">
          Deleting your account is permanent. Your conversations, credits and payment history will be erased.
        </p>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" data-testid="delete-account-btn">Delete account</Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete your account?</AlertDialogTitle>
              <AlertDialogDescription>
                This action cannot be undone. All your data will be permanently removed.
                Type <span className="font-mono font-semibold text-destructive">DELETE</span> below to confirm.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Type DELETE"
              data-testid="delete-confirm-input"
            />
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => setConfirmText('')}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={deleteAccount}
                disabled={confirmText !== 'DELETE' || deleting}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                data-testid="delete-confirm-btn"
              >
                {deleting ? 'Deleting...' : 'Permanently delete'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}
