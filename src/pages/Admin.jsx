import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Users as UsersIcon, MessageSquare, Zap, DollarSign, Search, Shield, ShieldOff, Ban, CheckCircle2, Plus, Database, Sliders } from 'lucide-react';
import { FinancePanel, ProvidersPanel, QueriesPanel, PricingPanel, PlansPanel, DiscountsPanel, SubscriptionsPanel } from './AdminPanels';
import { toast } from 'sonner';
import { format } from 'date-fns';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';

export default function Admin() {
  const [stats, setStats] = useState(null);
  const [tab, setTab] = useState('users');

  useEffect(() => { api.get('/admin/stats').then((r) => setStats(r.data)); }, []);

  return (
    <div className="p-6 md:p-8 max-w-7xl">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-medium tracking-tight">Admin Dashboard</h1>
        <p className="text-muted-foreground mt-1">Manage users, wallets, packs and transactions.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {stats ? (
          <>
            <StatCard label="Users" value={stats.total_users} Icon={UsersIcon} />
            <StatCard label="Conversations" value={stats.total_conversations} Icon={MessageSquare} />
            <StatCard label="AI Requests" value={stats.total_ai_requests} Icon={Zap} />
            <StatCard label="Paid transactions" value={stats.revenue?.reduce((s, r) => s + r.count, 0) || 0} Icon={DollarSign} />
          </>
        ) : [...Array(4)].map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="finance" data-testid="admin-tab-finance">Finance</TabsTrigger>
          <TabsTrigger value="providers" data-testid="admin-tab-providers">Providers</TabsTrigger>
          <TabsTrigger value="queries" data-testid="admin-tab-queries">Queries</TabsTrigger>
          <TabsTrigger value="pricing" data-testid="admin-tab-pricing">Pricing</TabsTrigger>
          <TabsTrigger value="plans" data-testid="admin-tab-plans">Plans</TabsTrigger>
          <TabsTrigger value="discounts" data-testid="admin-tab-discounts">Discounts</TabsTrigger>
          <TabsTrigger value="subs" data-testid="admin-tab-subs">Subscriptions</TabsTrigger>
          <TabsTrigger value="packs">Packs</TabsTrigger>
          <TabsTrigger value="transactions">Transactions</TabsTrigger>
          <TabsTrigger value="kb" data-testid="admin-tab-kb">Data Lake</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="mt-6"><UsersPanel /></TabsContent>
        <TabsContent value="finance" className="mt-6"><FinancePanel /></TabsContent>
        <TabsContent value="providers" className="mt-6"><ProvidersPanel /></TabsContent>
        <TabsContent value="queries" className="mt-6"><QueriesPanel /></TabsContent>
        <TabsContent value="pricing" className="mt-6"><PricingPanel /></TabsContent>
        <TabsContent value="plans" className="mt-6"><PlansPanel /></TabsContent>
        <TabsContent value="discounts" className="mt-6"><DiscountsPanel /></TabsContent>
        <TabsContent value="subs" className="mt-6"><SubscriptionsPanel /></TabsContent>
        <TabsContent value="packs" className="mt-6"><PacksPanel /></TabsContent>
        <TabsContent value="transactions" className="mt-6"><TransactionsPanel /></TabsContent>
        <TabsContent value="kb" className="mt-6"><KnowledgePanel /></TabsContent>
      </Tabs>
    </div>
  );
}

function KnowledgePanel() {
  const [stats, setStats] = useState(null);
  const [settings, setSettings] = useState(null);
  const [threshold, setThreshold] = useState(0.85);
  const [enabled, setEnabled] = useState(true);
  const [onlyMode, setOnlyMode] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const [s, cfg] = await Promise.all([api.get('/admin/kb/stats'), api.get('/admin/settings')]);
    setStats(s.data); setSettings(cfg.data);
    setThreshold(cfg.data.settings.kb_similarity_threshold ?? 0.85);
    setEnabled(cfg.data.settings.kb_enabled ?? true);
    setOnlyMode(cfg.data.settings.kb_only_mode ?? false);
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.post('/admin/settings', { key: 'kb_similarity_threshold', value: threshold });
      await api.post('/admin/settings', { key: 'kb_enabled', value: enabled });
      await api.post('/admin/settings', { key: 'kb_only_mode', value: onlyMode });
      toast.success('Settings saved');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Save failed'); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-6" data-testid="admin-kb-panel">
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Database className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-medium">Knowledge Bank Stats</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-muted-foreground">Total entries</div>
            <div className="text-2xl font-medium mt-1" data-testid="admin-kb-total-entries">{stats?.total_entries ?? '—'}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Cache hits (all-time)</div>
            <div className="text-2xl font-medium mt-1 text-emerald-500" data-testid="admin-kb-total-hits">{stats?.total_hits ?? '—'}</div>
          </div>
          <div className="col-span-2 md:col-span-2">
            <div className="text-xs text-muted-foreground mb-2">By kind</div>
            <div className="space-y-1 text-xs">
              {stats && Object.entries(stats.by_kind || {}).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-muted-foreground">{k}</span>
                  <span>{v.count} entries · {v.hits} hits</span>
                </div>
              ))}
              {stats && Object.keys(stats.by_kind || {}).length === 0 && (
                <span className="text-muted-foreground">No entries yet.</span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Sliders className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-medium">Retrieval Settings</h3>
        </div>
        <div className="space-y-5">
          <div>
            <div className="flex justify-between items-baseline mb-2">
              <Label className="text-xs">Semantic similarity threshold</Label>
              <span className="text-sm font-mono" data-testid="admin-kb-threshold-value">{threshold.toFixed(2)}</span>
            </div>
            <input
              type="range" min="0" max="1" step="0.01"
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              className="w-full accent-primary"
              data-testid="admin-kb-threshold-slider"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
              <span>Aggressive reuse · saves credits</span>
              <span>Safer answers · fewer hits</span>
            </div>
          </div>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)}
              className="w-4 h-4 accent-primary" data-testid="admin-kb-enabled-toggle"
            />
            <div>
              <div className="text-sm">Data Lake retrieval enabled</div>
              <div className="text-xs text-muted-foreground">Turn off to force all AI calls to hit the LLM.</div>
            </div>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox" checked={onlyMode} onChange={(e) => setOnlyMode(e.target.checked)}
              className="w-4 h-4 accent-primary" data-testid="admin-kb-only-toggle"
            />
            <div>
              <div className="text-sm">Knowledge-only mode (endgame)</div>
              <div className="text-xs text-muted-foreground">Zero third-party dependency — LLM calls fail unless the KB has an answer.</div>
            </div>
          </label>
          <Button onClick={save} disabled={saving} data-testid="admin-kb-save-btn">
            {saving ? 'Saving…' : 'Save settings'}
          </Button>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, Icon }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-primary" strokeWidth={1.75} />
      </div>
      <div className="font-display text-3xl font-medium">{value?.toLocaleString?.() || value}</div>
    </div>
  );
}

function UsersPanel() {
  const [users, setUsers] = useState([]);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [adjustFor, setAdjustFor] = useState(null);
  const [amount, setAmount] = useState(100);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/admin/users?q=${encodeURIComponent(q)}`);
      setUsers(data.items);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggle = async (id) => { await api.post(`/admin/users/${id}/toggle-active`); load(); };
  const promote = async (id) => { await api.post(`/admin/users/${id}/promote`); load(); };
  const adjust = async () => {
    try {
      await api.post('/admin/wallet/adjust', { user_id: adjustFor.id, amount, bucket: 'bonus' });
      toast.success(`Added ${amount} credits to ${adjustFor.email}`);
      setAdjustFor(null); load();
    } catch { toast.error('Failed'); }
  };

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="p-4 border-b border-border flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="h-3.5 w-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
          <Input placeholder="Search users" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8 h-8" />
        </div>
        <Button size="sm" onClick={load}>Search</Button>
      </div>
      {loading ? (
        <div className="p-6 space-y-2">{[...Array(5)].map((_,i) => <Skeleton key={i} className="h-12 rounded-md" />)}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted-foreground border-b border-border">
              <tr>
                <th className="text-left px-4 py-2">User</th>
                <th className="text-left px-4 py-2">Role</th>
                <th className="text-left px-4 py-2">Credits</th>
                <th className="text-left px-4 py-2">Status</th>
                <th className="text-right px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3">
                    <div className="font-medium">{u.name}</div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </td>
                  <td className="px-4 py-3"><Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>{u.role}</Badge></td>
                  <td className="px-4 py-3 font-mono">{Math.floor(u.credits_total || 0)}</td>
                  <td className="px-4 py-3">{u.is_active ? <Badge variant="outline" className="text-emerald-400 border-emerald-400/30">Active</Badge> : <Badge variant="outline" className="text-destructive border-destructive/30">Disabled</Badge>}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setAdjustFor(u)}>+ Credits</Button>
                      <Button size="sm" variant="ghost" onClick={() => promote(u.id)} title="Toggle admin">
                        {u.role === 'admin' ? <ShieldOff className="h-3.5 w-3.5" /> : <Shield className="h-3.5 w-3.5" />}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => toggle(u.id)}>
                        {u.is_active ? <Ban className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Dialog open={!!adjustFor} onOpenChange={(o) => !o && setAdjustFor(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add bonus credits to {adjustFor?.email}</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label>Amount</Label>
            <Input type="number" value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdjustFor(null)}>Cancel</Button>
            <Button onClick={adjust}>Add {amount} credits</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PacksPanel() {
  const [packs, setPacks] = useState([]);
  const [editing, setEditing] = useState(null);   // pack row being edited or 'new'
  const [busy, setBusy] = useState(false);

  const load = () => api.get('/packs/all').then((r) => setPacks(r.data.items));
  useEffect(() => { load(); }, []);

  const save = async (payload, id) => {
    setBusy(true);
    try {
      if (id) await api.patch(`/packs/${id}`, payload);
      else    await api.post('/packs/', payload);
      toast.success(id ? 'Pack updated' : 'Pack created');
      setEditing(null);
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed');
    } finally { setBusy(false); }
  };

  const remove = async (p) => {
    if (!window.confirm(`Delete ${p.name} (${p.currency}) — this can\u2019t be undone.`)) return;
    setBusy(true);
    try {
      await api.delete(`/packs/${p.id}`);
      toast.success('Pack deleted');
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Delete failed');
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {packs.length} pack{packs.length !== 1 ? 's' : ''} — edit any field or create new ones. Changes take effect immediately for buyers.
        </p>
        <Button size="sm" onClick={() => setEditing('new')} data-testid="admin-pack-new-btn">
          <Plus className="h-4 w-4 mr-1" /> New pack
        </Button>
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted-foreground border-b border-border">
              <tr>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Slug</th>
                <th className="text-left px-4 py-2">Price</th>
                <th className="text-left px-4 py-2">Credits</th>
                <th className="text-left px-4 py-2">Bonus</th>
                <th className="text-left px-4 py-2">Currency</th>
                <th className="text-left px-4 py-2">Popular</th>
                <th className="text-left px-4 py-2">Visible</th>
                <th className="text-left px-4 py-2">Order</th>
                <th className="text-left px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {packs.map((p) => (
                <tr key={p.id} className="hover:bg-muted/40">
                  <td className="px-4 py-3 font-medium">{p.name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">{p.slug}</td>
                  <td className="px-4 py-3 font-mono">{p.currency === 'usd' ? '$' : '\u20b9'}{p.price}</td>
                  <td className="px-4 py-3 font-mono">{p.credits}</td>
                  <td className="px-4 py-3 font-mono">{p.bonus_credits}</td>
                  <td className="px-4 py-3 uppercase text-xs">{p.currency}</td>
                  <td className="px-4 py-3">{p.is_popular ? '\u2605' : ''}</td>
                  <td className="px-4 py-3">{p.is_visible ? '\u2713' : '\u2014'}</td>
                  <td className="px-4 py-3 font-mono">{p.sort_order}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(p)}
                            data-testid={`admin-pack-edit-${p.slug}`}>Edit</Button>
                    <Button size="sm" variant="ghost" className="text-red-500 hover:text-red-600"
                            onClick={() => remove(p)} disabled={busy}
                            data-testid={`admin-pack-delete-${p.slug}`}>Delete</Button>
                  </td>
                </tr>
              ))}
              {packs.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">
                  No packs — create one to make it purchasable.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {editing && (
        <PackFormDialog pack={editing === 'new' ? null : editing}
                        onClose={() => setEditing(null)}
                        onSave={save} busy={busy} />
      )}
    </div>
  );
}

function PackFormDialog({ pack, onClose, onSave, busy }) {
  const [form, setForm] = useState({
    name: pack?.name || '',
    slug: pack?.slug || '',
    description: pack?.description || '',
    price: pack?.price ?? 0,
    currency: pack?.currency || 'usd',
    credits: pack?.credits ?? 0,
    bonus_credits: pack?.bonus_credits ?? 0,
    is_popular: !!pack?.is_popular,
    is_visible: pack?.is_visible !== false,
    sort_order: pack?.sort_order ?? 99,
  });
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = (e) => {
    e.preventDefault();
    const payload = {
      ...form,
      price: parseFloat(form.price) || 0,
      credits: parseFloat(form.credits) || 0,
      bonus_credits: parseFloat(form.bonus_credits) || 0,
      sort_order: parseInt(form.sort_order) || 99,
    };
    onSave(payload, pack?.id);
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="admin-pack-form">
        <DialogHeader>
          <DialogTitle>{pack ? `Edit ${pack.name}` : 'New credit pack'}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-3">
          <div className="space-y-1 col-span-1"><Label>Name</Label>
            <Input value={form.name} onChange={(e) => set('name')(e.target.value)} required data-testid="pack-form-name" /></div>
          <div className="space-y-1 col-span-1"><Label>Slug</Label>
            <Input value={form.slug} onChange={(e) => set('slug')(e.target.value)} required
                   disabled={!!pack} placeholder="starter-usd" data-testid="pack-form-slug" /></div>
          <div className="space-y-1 col-span-2"><Label>Description</Label>
            <Input value={form.description} onChange={(e) => set('description')(e.target.value)} /></div>
          <div className="space-y-1"><Label>Price</Label>
            <Input type="number" step="0.01" value={form.price}
                   onChange={(e) => set('price')(e.target.value)} data-testid="pack-form-price" /></div>
          <div className="space-y-1"><Label>Currency</Label>
            <select className="h-10 w-full rounded-md border border-input bg-background px-3"
                    value={form.currency} onChange={(e) => set('currency')(e.target.value)} disabled={!!pack}>
              <option value="usd">USD</option><option value="inr">INR</option>
            </select></div>
          <div className="space-y-1"><Label>Credits</Label>
            <Input type="number" value={form.credits}
                   onChange={(e) => set('credits')(e.target.value)} data-testid="pack-form-credits" /></div>
          <div className="space-y-1"><Label>Bonus credits</Label>
            <Input type="number" value={form.bonus_credits}
                   onChange={(e) => set('bonus_credits')(e.target.value)} /></div>
          <div className="space-y-1"><Label>Sort order</Label>
            <Input type="number" value={form.sort_order}
                   onChange={(e) => set('sort_order')(e.target.value)} /></div>
          <div className="space-y-1"><Label>Visible / popular</Label>
            <div className="flex items-center gap-4 pt-2 text-sm">
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={form.is_visible}
                onChange={(e) => set('is_visible')(e.target.checked)} /> Visible</label>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={form.is_popular}
                onChange={(e) => set('is_popular')(e.target.checked)} /> Popular</label>
            </div>
          </div>
          <DialogFooter className="col-span-2 mt-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy} data-testid="pack-form-save">
              {busy ? 'Saving\u2026' : (pack ? 'Save changes' : 'Create pack')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TransactionsPanel() {
  const [txs, setTxs] = useState([]);
  useEffect(() => { api.get('/admin/transactions').then((r) => setTxs(r.data.items)); }, []);
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-muted-foreground border-b border-border">
            <tr>
              <th className="text-left px-4 py-2">Provider</th>
              <th className="text-left px-4 py-2">Pack</th>
              <th className="text-left px-4 py-2">Amount</th>
              <th className="text-left px-4 py-2">Credits</th>
              <th className="text-left px-4 py-2">Status</th>
              <th className="text-left px-4 py-2">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {txs.map((t) => (
              <tr key={t.id}>
                <td className="px-4 py-3 uppercase text-xs">{t.provider}</td>
                <td className="px-4 py-3">{t.pack_slug}</td>
                <td className="px-4 py-3 font-mono">{t.currency === 'usd' ? '$' : '₹'}{t.amount}</td>
                <td className="px-4 py-3 font-mono">{t.credits}</td>
                <td className="px-4 py-3"><Badge variant={t.status === 'paid' ? 'default' : 'secondary'}>{t.status}</Badge></td>
                <td className="px-4 py-3 text-xs text-muted-foreground">{format(new Date(t.created_at), 'PP p')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
