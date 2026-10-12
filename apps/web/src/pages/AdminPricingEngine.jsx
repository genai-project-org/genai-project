import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

const CHANNELS = [
  ['razorpay', 'Razorpay (2% + GST)'],
  ['apple', 'Apple App Store'],
  ['google', 'Google Play'],
];

/**
 * Admin > Packs & Pricing. The admin sets only the target profit margin and the per-channel
 * commissions; the engine derives credits/USD, pack credits and clean USD/INR prices from the
 * service cost catalog. Preview is a dry run; "Apply & publish" writes the packs everyone sees.
 */
export default function PackPricingPanel() {
  const [cfg, setCfg] = useState(null);
  const [table, setTable] = useState(null);
  const [publishedAt, setPublishedAt] = useState(null);
  const [busy, setBusy] = useState(null);

  const patchBody = () => ({
    target_margin_pct: parseFloat(cfg.target_margin_pct),
    margin_floor_pct: parseFloat(cfg.margin_floor_pct),
    commissions_pct: Object.fromEntries(Object.entries(cfg.commissions_pct).map(([k, v]) => [k, parseFloat(v)])),
    inr_round_step: parseInt(cfg.inr_round_step, 10),
  });

  const err = (e) => toast.error(e.response?.data?.detail || 'Request failed');

  const preview = async (body) => {
    setBusy('preview');
    try { setTable((await api.post('/pricing/admin/preview', body)).data); }
    catch (e) { err(e); }
    finally { setBusy(null); }
  };

  useEffect(() => {
    (async () => {
      const { data } = await api.get('/pricing/admin/config');
      setCfg(data.config); setPublishedAt(data.published_at);
      preview({});
    })().catch(err);
    // eslint-disable-next-line
  }, []);

  const publish = async () => {
    if (!window.confirm('Publish these packs? This replaces the current packs and the pay-as-you-go rate for every user and app.')) return;
    setBusy('publish');
    try {
      const { data } = await api.post('/pricing/admin/publish', patchBody());
      setTable(data); setPublishedAt(new Date().toISOString());
      toast.success('Packs published');
    } catch (e) { err(e); }
    finally { setBusy(null); }
  };

  const download = async (fmt) => {
    try {
      const { data } = await api.get(`/pricing/admin/export?format=${fmt}`, { responseType: 'text', transformResponse: (r) => r });
      const blob = new Blob([data], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `iema-store-products.${fmt}`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { err(e); }
  };

  const copyMd = async () => {
    try {
      const { data } = await api.get('/pricing/admin/export?format=md', { responseType: 'text', transformResponse: (r) => r });
      await navigator.clipboard.writeText(data);
      toast.success('Markdown copied');
    } catch (e) { err(e); }
  };

  if (!cfg) return <div className="text-sm text-muted-foreground">Loading...</div>;
  const setField = (k, v) => setCfg({ ...cfg, [k]: v });

  return (
    <div className="space-y-6" data-testid="admin-pack-pricing">
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <Label>Target profit margin %</Label>
            <Input type="number" value={cfg.target_margin_pct} data-testid="pp-margin"
              onChange={(e) => setField('target_margin_pct', e.target.value)} />
          </div>
          {CHANNELS.map(([k, label]) => (
            <div key={k}>
              <Label>{label} commission %</Label>
              <Input type="number" value={cfg.commissions_pct[k] ?? 0} data-testid={`pp-comm-${k}`}
                onChange={(e) => setField('commissions_pct', { ...cfg.commissions_pct, [k]: e.target.value })} />
            </div>
          ))}
          <div>
            <Label>Margin floor % (bonus cap)</Label>
            <Input type="number" value={cfg.margin_floor_pct} onChange={(e) => setField('margin_floor_pct', e.target.value)} />
          </div>
          <div>
            <Label>INR rounding step</Label>
            <Input type="number" value={cfg.inr_round_step} onChange={(e) => setField('inr_round_step', e.target.value)} />
          </div>
        </div>
        <p className="text-xs text-muted-foreground mt-3">
          Prices are set against the highest-commission channel so the target margin holds everywhere. Pay-as-you-go minimum is fixed at $20.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => preview(patchBody())} disabled={!!busy} data-testid="pp-preview">
            {busy === 'preview' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Preview'}
          </Button>
          <Button onClick={publish} disabled={!!busy} data-testid="pp-publish">
            {busy === 'publish' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Apply & publish'}
          </Button>
          <span className="text-xs text-muted-foreground self-center">
            {publishedAt ? `Last published ${new Date(publishedAt).toLocaleString()}` : 'Not published yet'}
          </span>
        </div>
      </div>

      {table && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <Stat label="Provider cost / credit" value={`$${table.cost_per_credit_usd}`} />
            <Stat label="Price / credit (basis)" value={`$${table.price_per_credit_usd}`} />
            <Stat label="Credits per $1 (PAYG + packs)" value={table.credits_per_usd} />
            <Stat label="USD to INR" value={table.fx_rate} />
          </div>

          <div className="rounded-xl border border-border bg-card overflow-x-auto">
            <table className="w-full text-sm" data-testid="pp-table">
              <thead className="text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  {['Pack', 'Type', 'Credits', 'USD', 'INR', 'Store product ID', 'Margin after commission', 'vs PAYG'].map((h) => (
                    <th key={h} className="text-left p-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.packs.map((p) => (
                  <tr key={p.slug} className="border-t border-border/60">
                    <td className="p-3 font-medium">{p.name}</td>
                    <td className="p-3 text-muted-foreground">{p.kind}{p.category ? ` / ${p.category}` : ''}</td>
                    <td className="p-3">{p.total_credits.toLocaleString()}{p.bonus_credits > 0 && <span className="text-emerald-400"> (+{p.bonus_credits})</span>}</td>
                    <td className="p-3">${p.price_usd.toFixed(2)}</td>
                    <td className="p-3">{'₹'}{p.price_inr.toLocaleString('en-IN')}</td>
                    <td className="p-3 font-mono text-xs">{p.product_id}</td>
                    <td className="p-3 text-xs">
                      {Object.entries(p.margin_pct).map(([ch, m]) => (
                        <span key={ch} className="mr-3">{ch} <b>{m}%</b></span>
                      ))}
                    </td>
                    <td className="p-3 text-emerald-400">+{p.value_vs_payg_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">Store setup export (published packs):</span>
            <Button size="sm" variant="outline" onClick={() => download('csv')}>CSV</Button>
            <Button size="sm" variant="outline" onClick={() => download('json')}>JSON</Button>
            <Button size="sm" variant="outline" onClick={() => download('md')}>Markdown</Button>
            <Button size="sm" variant="outline" onClick={copyMd}>Copy Markdown</Button>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-display text-xl font-medium mt-1">{value}</div>
    </div>
  );
}
