import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from 'sonner';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar, CartesianGrid } from 'recharts';
import { DollarSign, TrendingUp, TrendingDown, Search, Coins, Sparkles, Zap } from 'lucide-react';

const PERIODS = [
  { key: '24h', label: '24h' }, { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' }, { key: '90d', label: '90 days' },
];

// ---------------- FINANCE ----------------
export function FinancePanel() {
  const [period, setPeriod] = useState('30d');
  const [data, setData] = useState(null);
  const [providers, setProviders] = useState([]);
  const [timeseries, setTimeseries] = useState([]);
  useEffect(() => {
    (async () => {
      const [f, p, t] = await Promise.all([
        api.get(`/admin/analytics/finance?period=${period}`),
        api.get(`/admin/analytics/provider-usage?period=${period}`),
        api.get(`/admin/analytics/timeseries?period=${period}`),
      ]);
      setData(f.data); setProviders(p.data.items || []); setTimeseries(t.data.items || []);
    })();
  }, [period]);
  const totalExpense = data?.expense_usd || 0;
  const totalIncome = data?.income_usd_estimate || 0;
  const margin = data?.margin_usd_estimate || 0;

  // Aggregate by bucket
  const byBucket = {};
  timeseries.forEach((row) => {
    byBucket[row.bucket] ||= { bucket: row.bucket, cost_usd: 0 };
    byBucket[row.bucket].cost_usd += row.cost_usd;
  });
  const timelineArr = Object.values(byBucket).sort((a, b) => a.bucket.localeCompare(b.bucket));

  return (
    <div className="space-y-6" data-testid="admin-finance-panel">
      <Tabs value={period} onValueChange={setPeriod}>
        <TabsList>{PERIODS.map(p => <TabsTrigger key={p.key} value={p.key}>{p.label}</TabsTrigger>)}</TabsList>
      </Tabs>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard icon={TrendingDown} label="LLM Expense (est USD)" value={`$${totalExpense.toFixed(4)}`} sub={`period: ${period}`} tone="red" testid="admin-finance-expense" />
        <StatCard icon={TrendingUp} label="Income (est USD)" value={`$${totalIncome.toFixed(4)}`} sub={`~₹${data?.income_inr_estimate?.toFixed(2)}`} tone="green" testid="admin-finance-income" />
        <StatCard icon={DollarSign} label="Margin" value={`$${margin.toFixed(4)}`} sub={margin >= 0 ? 'Profitable' : 'Loss'} tone={margin >= 0 ? 'green' : 'red'} testid="admin-finance-margin" />
      </div>
      <div className="rounded-xl border border-border bg-card p-6">
        <h3 className="font-display text-base font-medium mb-4">LLM expense over time (USD)</h3>
        <div className="h-64">
          <ResponsiveContainer>
            <LineChart data={timelineArr}>
              <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
              <XAxis dataKey="bucket" stroke="hsl(var(--muted-foreground))" fontSize={10} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={10} />
              <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }} />
              <Line type="monotone" dataKey="cost_usd" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

// ---------------- PROVIDERS ----------------
const COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#0ea5e9', '#a855f7'];
export function ProvidersPanel() {
  const [period, setPeriod] = useState('30d');
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.get(`/admin/analytics/provider-usage?period=${period}`).then(r => setItems(r.data.items || []));
  }, [period]);
  return (
    <div className="space-y-6" data-testid="admin-providers-panel">
      <Tabs value={period} onValueChange={setPeriod}>
        <TabsList>{PERIODS.map(p => <TabsTrigger key={p.key} value={p.key}>{p.label}</TabsTrigger>)}</TabsList>
      </Tabs>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-xl border border-border bg-card p-6">
          <h3 className="font-display text-base font-medium mb-4">Credit spend by provider</h3>
          <div className="h-64">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={items} dataKey="credits" nameKey="provider" innerRadius={45} outerRadius={90} paddingAngle={2}>
                  {items.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-6 overflow-x-auto">
          <h3 className="font-display text-base font-medium mb-4">Details</h3>
          <table className="w-full text-sm" data-testid="admin-providers-table">
            <thead className="text-xs uppercase tracking-wider text-muted-foreground border-b border-border">
              <tr>
                <th className="text-left py-2">Provider</th>
                <th className="text-right py-2">Credits</th>
                <th className="text-right py-2">Cost USD</th>
                <th className="text-right py-2">Calls</th>
                <th className="text-right py-2">KB hits</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.provider} className="border-b border-border/50 last:border-0">
                  <td className="py-2 font-medium">{it.provider}</td>
                  <td className="py-2 text-right">{Math.floor(it.credits)}</td>
                  <td className="py-2 text-right">${(it.cost_usd || 0).toFixed(3)}</td>
                  <td className="py-2 text-right">{it.calls}</td>
                  <td className="py-2 text-right text-emerald-500">{it.kb_hits}</td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-muted-foreground text-xs">No usage yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------- QUERIES ----------------
export function QueriesPanel() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState('');
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState(null);

  const load = async () => {
    const { data } = await api.get(`/admin/queries?limit=50${q ? `&q=${encodeURIComponent(q)}` : ''}`);
    setItems(data.items || []); setTotal(data.total || 0);
  };
  useEffect(() => { load(); }, []);
  return (
    <div className="space-y-4" data-testid="admin-queries-panel">
      <div className="flex gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search prompts/messages…" onKeyDown={(e) => e.key === 'Enter' && load()} data-testid="admin-queries-search" />
        <Button onClick={load} data-testid="admin-queries-search-btn"><Search className="h-4 w-4 mr-2" /> Search</Button>
      </div>
      <div className="text-xs text-muted-foreground">{total.toLocaleString()} events</div>
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wider text-muted-foreground border-b border-border">
            <tr>
              <th className="text-left px-3 py-2">Event</th>
              <th className="text-left px-3 py-2">User</th>
              <th className="text-left px-3 py-2">Payload</th>
              <th className="text-left px-3 py-2">When</th>
            </tr>
          </thead>
          <tbody>
            {items.map(it => (
              <tr key={it.id} onClick={() => setSelected(it)} className="border-b border-border/50 last:border-0 hover:bg-accent/40 cursor-pointer">
                <td className="px-3 py-2 whitespace-nowrap"><span className="text-primary">{it.event_type}</span></td>
                <td className="px-3 py-2 text-xs text-muted-foreground truncate max-w-[140px]">{(it.user_id || '—').slice(0, 10)}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground truncate max-w-[400px]">{JSON.stringify(it.payload).slice(0, 120)}</td>
                <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground">{new Date(it.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={4} className="py-6 text-center text-muted-foreground text-xs">No queries.</td></tr>}
          </tbody>
        </table>
      </div>
      {selected && (
        <div className="rounded-xl border border-primary/30 bg-card p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="font-medium">{selected.event_type}</span>
            <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>Close</Button>
          </div>
          <pre className="text-xs bg-[hsl(var(--surface))] rounded p-3 overflow-x-auto">{JSON.stringify(selected.payload, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

// ---------------- PRICING ----------------
export function PricingPanel() {
  const [items, setItems] = useState([]);
  const [edits, setEdits] = useState({});
  const load = async () => {
    const { data } = await api.get('/admin/pricing');
    setItems(data.items || []);
  };
  useEffect(() => { load(); }, []);
  const save = async (svc) => {
    try {
      await api.patch(`/admin/pricing/${svc}`, { credit_cost: parseFloat(edits[svc]) });
      toast.success(`Saved ${svc}`);
      setEdits(e => { const n = { ...e }; delete n[svc]; return n; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="admin-pricing-panel">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wider text-muted-foreground border-b border-border">
          <tr>
            <th className="text-left px-3 py-2">Service</th>
            <th className="text-left px-3 py-2">Description</th>
            <th className="text-left px-3 py-2">Provider</th>
            <th className="text-left px-3 py-2 w-40">Credits / call</th>
            <th className="w-20"></th>
          </tr>
        </thead>
        <tbody>
          {items.map(it => (
            <tr key={it.service_key} className="border-b border-border/50 last:border-0">
              <td className="px-3 py-2 font-mono text-xs">{it.service_key}</td>
              <td className="px-3 py-2 text-xs text-muted-foreground">{it.description}</td>
              <td className="px-3 py-2 text-xs">{it.provider}</td>
              <td className="px-3 py-2">
                <Input
                  type="number" step="0.5" min="0" max="10000"
                  value={edits[it.service_key] ?? it.credit_cost}
                  onChange={(e) => setEdits({ ...edits, [it.service_key]: e.target.value })}
                  className="h-8 text-sm"
                  data-testid={`admin-pricing-${it.service_key}`}
                />
              </td>
              <td className="px-3 py-2 text-right">
                {edits[it.service_key] !== undefined && edits[it.service_key] !== String(it.credit_cost) && (
                  <Button size="sm" onClick={() => save(it.service_key)} data-testid={`admin-pricing-save-${it.service_key}`}>Save</Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------- PLANS ----------------
export function PlansPanel() {
  const [items, setItems] = useState([]);
  const [edits, setEdits] = useState({});
  const [showNew, setShowNew] = useState(false);
  const load = async () => {
    const { data } = await api.get('/admin/plans');
    setItems(data.items || []);
  };
  useEffect(() => { load(); }, []);
  const patch = (id, field, value) => setEdits(e => ({ ...e, [id]: { ...(e[id] || {}), [field]: value } }));
  const save = async (id) => {
    try {
      const body = edits[id] || {};
      const clean = {};
      Object.entries(body).forEach(([k, v]) => {
        if (k === 'name' || k === 'billing_period') clean[k] = v;
        else clean[k] = k === 'is_free' || k === 'one_time' ? Boolean(v) : parseFloat(v);
      });
      await api.patch(`/admin/plans/${id}`, clean);
      toast.success(`Saved ${id}`);
      setEdits(e => { const n = { ...e }; delete n[id]; return n; });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };
  const del = async (id) => {
    if (!window.confirm(`Delete plan "${id}"?`)) return;
    try {
      await api.delete(`/admin/plans/${id}`);
      toast.success('Deleted'); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };
  return (
    <div className="space-y-4" data-testid="admin-plans-panel">
      <div className="flex justify-end">
        <Button onClick={() => setShowNew(true)} data-testid="admin-plan-new-btn"><Coins className="h-4 w-4 mr-2" /> New plan</Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {items.map(p => {
          const e = edits[p.plan_id] || {};
          const val = (f) => e[f] !== undefined ? e[f] : p[f];
          return (
            <div key={p.plan_id} className="rounded-xl border border-border bg-card p-5 space-y-3">
              <div className="flex items-center gap-2">
                <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center"><Coins className="h-4 w-4 text-primary" /></div>
                <Input value={val('name') || ''} onChange={(ev) => patch(p.plan_id, 'name', ev.target.value)} className="text-lg font-medium h-9 border-none px-0" />
                {p.plan_id !== 'free' && (
                  <button onClick={() => del(p.plan_id)} className="text-muted-foreground hover:text-destructive text-xs" data-testid={`admin-plan-delete-${p.plan_id}`}>Delete</button>
                )}
              </div>
              <PlanField label="Monthly credits" value={val('monthly_credits')} onChange={(v) => patch(p.plan_id, 'monthly_credits', v)} testid={`admin-plan-${p.plan_id}-monthly`} />
              <PlanField label="Window hours" value={val('window_hours')} onChange={(v) => patch(p.plan_id, 'window_hours', v)} testid={`admin-plan-${p.plan_id}-hours`} />
              <PlanField label="Credits / window" value={val('window_credits')} onChange={(v) => patch(p.plan_id, 'window_credits', v)} testid={`admin-plan-${p.plan_id}-cap`} />
              <PlanField label="Price $ (USD)" value={val('price_usd')} onChange={(v) => patch(p.plan_id, 'price_usd', v)} testid={`admin-plan-${p.plan_id}-price`} disabled />
              <div>
                <Label className="text-xs text-muted-foreground">Billing period</Label>
                <select value={val('billing_period') || 'monthly'} disabled
                  className="w-full h-8 mt-1 text-sm rounded-md border border-border bg-background px-2 disabled:opacity-50 disabled:cursor-not-allowed">
                  <option value="one_time">One-time</option>
                  <option value="monthly">Monthly</option>
                  <option value="annual">Annual</option>
                </select>
              </div>
              {edits[p.plan_id] && <Button size="sm" onClick={() => save(p.plan_id)} data-testid={`admin-plan-save-${p.plan_id}`}>Save</Button>}
            </div>
          );
        })}
      </div>
      {showNew && <NewPlanModal onClose={() => setShowNew(false)} onCreated={() => { setShowNew(false); load(); }} />}
    </div>
  );
}

function NewPlanModal({ onClose, onCreated }) {
  const [form, setForm] = useState({ plan_id: '', name: '', monthly_credits: 500, window_hours: 5, window_credits: 100, price_usd: 9.99, billing_period: 'monthly' });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post('/admin/plans', form);
      toast.success('Plan created'); onCreated();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
    finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" data-testid="admin-plan-new-modal">
      <div className="bg-card border border-border rounded-xl p-6 max-w-md w-full space-y-3">
        <h3 className="font-display text-lg font-medium">New plan</h3>
        <div>
          <Label className="text-xs text-muted-foreground">Plan ID</Label>
          <Input placeholder="plan_id (e.g. starter)" value={form.plan_id} onChange={(e) => setForm({ ...form, plan_id: e.target.value })} className="mt-1" data-testid="admin-plan-new-id" />
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Name</Label>
          <Input placeholder="Name (e.g. Starter)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1" data-testid="admin-plan-new-name" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label className="text-xs text-muted-foreground">Monthly credits</Label>
            <Input type="number" value={form.monthly_credits} onChange={(e) => setForm({ ...form, monthly_credits: parseFloat(e.target.value) })} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Price $ (USD)</Label>
            <Input type="number" value={form.price_usd} onChange={(e) => setForm({ ...form, price_usd: parseFloat(e.target.value) })} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Window hours</Label>
            <Input type="number" value={form.window_hours} onChange={(e) => setForm({ ...form, window_hours: parseInt(e.target.value) })} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Credits / window</Label>
            <Input type="number" value={form.window_credits} onChange={(e) => setForm({ ...form, window_credits: parseFloat(e.target.value) })} className="mt-1" />
          </div>
        </div>
        <div>
          <Label className="text-xs text-muted-foreground">Billing period</Label>
          <select value={form.billing_period} onChange={(e) => setForm({ ...form, billing_period: e.target.value })} className="w-full h-9 mt-1 text-sm rounded-md border border-border bg-background px-2">
            <option value="one_time">One-time</option><option value="monthly">Monthly</option><option value="annual">Annual</option>
          </select>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !form.plan_id || !form.name} data-testid="admin-plan-new-submit">Create</Button>
        </div>
      </div>
    </div>
  );
}

// ---------------- DISCOUNTS ----------------
export function DiscountsPanel() {
  const [items, setItems] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const load = async () => { const { data } = await api.get('/admin/discounts'); setItems(data.items || []); };
  useEffect(() => { load(); }, []);
  const del = async (code) => {
    if (!window.confirm(`Delete "${code}"?`)) return;
    try { await api.delete(`/admin/discounts/${code}`); toast.success('Deleted'); load(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };
  return (
    <div className="space-y-4" data-testid="admin-discounts-panel">
      <div className="flex justify-end">
        <Button onClick={() => setShowNew(true)} data-testid="admin-discount-new-btn">New discount</Button>
      </div>
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wider text-muted-foreground border-b border-border">
            <tr>
              <th className="text-left px-3 py-2">Code</th>
              <th className="text-left px-3 py-2">Discount</th>
              <th className="text-left px-3 py-2">Uses</th>
              <th className="text-left px-3 py-2">Applies to</th>
              <th className="text-left px-3 py-2">Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map(d => (
              <tr key={d.code} className="border-b border-border/50 last:border-0">
                <td className="px-3 py-2 font-mono text-xs">{d.code}</td>
                <td className="px-3 py-2 text-xs">{d.percent_off ? `${d.percent_off}% off` : `$${d.flat_off_usd} off`}</td>
                <td className="px-3 py-2 text-xs">{d.uses}/{d.max_uses || '∞'}</td>
                <td className="px-3 py-2 text-xs">{d.applies_to}</td>
                <td className="px-3 py-2 text-xs">{d.active ? <span className="text-emerald-500">yes</span> : <span className="text-muted-foreground">no</span>}</td>
                <td className="px-3 py-2 text-right">
                  <button onClick={() => del(d.code)} className="text-xs text-destructive" data-testid={`admin-discount-delete-${d.code}`}>Delete</button>
                </td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-muted-foreground text-xs">No discounts. Click "New discount".</td></tr>}
          </tbody>
        </table>
      </div>
      {showNew && <NewDiscountModal onClose={() => setShowNew(false)} onCreated={() => { setShowNew(false); load(); }} />}
    </div>
  );
}

function NewDiscountModal({ onClose, onCreated }) {
  const [form, setForm] = useState({ code: '', percent_off: 20, flat_off_usd: 0, max_uses: 0, applies_to: 'any', active: true });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try { await api.post('/admin/discounts', form); toast.success('Created'); onCreated(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
    finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-xl p-6 max-w-md w-full space-y-3">
        <h3 className="font-display text-lg font-medium">New discount code</h3>
        <div>
          <Label className="text-xs text-muted-foreground">Code</Label>
          <Input placeholder="Code (e.g. LAUNCH50)" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} className="mt-1" data-testid="admin-discount-new-code" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label className="text-xs text-muted-foreground">% off</Label>
            <Input type="number" placeholder="e.g. 20" value={form.percent_off} onChange={(e) => setForm({ ...form, percent_off: parseFloat(e.target.value) })} className="mt-1" data-testid="admin-discount-new-percent" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Flat $ off (USD)</Label>
            <Input type="number" placeholder="e.g. 5" value={form.flat_off_usd} onChange={(e) => setForm({ ...form, flat_off_usd: parseFloat(e.target.value) })} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Max uses (0 = ∞)</Label>
            <Input type="number" value={form.max_uses} onChange={(e) => setForm({ ...form, max_uses: parseInt(e.target.value) })} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">Applies to</Label>
            <Input placeholder="any | plan:pro" value={form.applies_to} onChange={(e) => setForm({ ...form, applies_to: e.target.value })} className="mt-1" />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !form.code} data-testid="admin-discount-new-submit">Create</Button>
        </div>
      </div>
    </div>
  );
}

// ---------------- SUBSCRIPTIONS ----------------
export function SubscriptionsPanel() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get('/admin/subscriptions').then(r => setItems(r.data.items || [])); }, []);
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden" data-testid="admin-subscriptions-panel">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wider text-muted-foreground border-b border-border">
          <tr>
            <th className="text-left px-3 py-2">User</th>
            <th className="text-left px-3 py-2">Plan</th>
            <th className="text-left px-3 py-2">Source</th>
            <th className="text-left px-3 py-2">Status</th>
            <th className="text-left px-3 py-2">Credits granted</th>
            <th className="text-left px-3 py-2">When</th>
          </tr>
        </thead>
        <tbody>
          {items.map(s => (
            <tr key={s.id} className="border-b border-border/50 last:border-0">
              <td className="px-3 py-2 text-xs">{s.email || s.user_id?.slice(0, 8)}</td>
              <td className="px-3 py-2 text-xs">{s.plan_id}</td>
              <td className="px-3 py-2 text-xs uppercase">{s.source}</td>
              <td className="px-3 py-2 text-xs"><span className={s.status === 'active' ? 'text-emerald-500' : 'text-muted-foreground'}>{s.status}</span></td>
              <td className="px-3 py-2 text-xs">{s.credits_granted || '—'}</td>
              <td className="px-3 py-2 text-xs">{new Date(s.granted_at || s.created_at).toLocaleString()}</td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-muted-foreground text-xs">No subscriptions yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function PlanField({ label, value, onChange, testid, disabled }) {
  return (
    <div>
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Input type="number" min="0" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className="h-8 mt-1 text-sm" data-testid={testid} />
    </div>
  );
}

function StatCard({ icon: Icon, label, value, sub, tone, testid }) {
  const toneCls = tone === 'green' ? 'text-emerald-500' : tone === 'red' ? 'text-red-500' : 'text-primary';
  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid={testid}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">{label}</span>
        <Icon className={`h-4 w-4 ${toneCls}`} />
      </div>
      <div className="font-display text-3xl font-medium">{value}</div>
      <div className="text-xs text-muted-foreground mt-1">{sub}</div>
    </div>
  );
}
