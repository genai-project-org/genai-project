import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Check, Loader2, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Skeleton } from '@/components/ui/skeleton';
import { BILLING } from '@/constants/testIds';
import { usePricing, loadPricing, fmtCredits, fmtInr, fmtUsd, inrFor } from '@/lib/pricing';
import PaygCard from '@/components/PaygCard';

// Two ways to add credits, one wallet: pay-as-you-go (any amount >= minimum) or a pack
// (a better-value / specialised bundle of the same credits). No subscriptions, no plan walls.
export default function Billing() {
  const { pricing, loading } = usePricing();
  const [buying, setBuying] = useState(null);
  const [code, setCode] = useState('');
  const [applied, setApplied] = useState(null);
  const [discounts, setDiscounts] = useState({});
  const [applying, setApplying] = useState(false);

  useEffect(() => { loadPricing(true).catch(() => {}); }, []);

  const packs = pricing?.packs || [];
  const general = packs.filter((p) => p.kind !== 'specialised');
  const specialised = packs.filter((p) => p.kind === 'specialised');

  const applyCode = async () => {
    const c = code.trim();
    if (!c) return;
    setApplying(true);
    try {
      const results = await Promise.all(packs.map((p) =>
        api.post('/payments/discount/validate', { code: c, pack_slug: p.slug })
          .then((r) => [p.slug, r.data]).catch(() => [p.slug, { ok: false }])));
      const map = Object.fromEntries(results);
      if (!Object.values(map).some((d) => d.ok)) {
        const reason = Object.values(map).find((d) => d.reason)?.reason;
        toast.error(reason ? `Code not valid: ${reason}` : 'Invalid or expired code');
        setDiscounts({}); setApplied(null);
      } else {
        setDiscounts(map); setApplied(c.toUpperCase());
        toast.success('Discount applied');
      }
    } finally { setApplying(false); }
  };
  const clearCode = () => { setCode(''); setApplied(null); setDiscounts({}); };

  const buyPack = async (pack) => {
    setBuying(pack.slug);
    try {
      const body = { pack_slug: pack.slug };
      if (applied && discounts[pack.slug]?.ok) body.discount_code = applied;
      const { data } = await api.post('/payments/razorpay/order', body);
      if (!data.short_url) {
        toast.error('No checkout URL returned from Razorpay');
        setBuying(null);
        return;
      }
      // Razorpay-hosted checkout (rzp.io): works even though our domain is not yet
      // approved on the merchant profile.
      window.location.href = data.short_url;
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to start payment');
      setBuying(null);
    }
  };

  const renderPack = (p) => {
    const d = discounts[p.slug];
    const discounted = applied && d?.ok;
    const usd = discounted ? d.final_usd : p.price_usd;
    const inr = discounted ? inrFor(d.final_usd, pricing) : p.price_inr;
    return (
      <div key={p.slug} data-testid={BILLING.packCard}
        className={`relative rounded-2xl border p-6 flex flex-col ${p.is_popular ? 'border-primary shadow-[0_0_30px_hsl(var(--primary)/0.15)]' : 'border-border'} bg-card`}>
        {p.is_popular && <Badge className="absolute -top-2 right-4">Most popular</Badge>}
        <div className="text-sm text-muted-foreground">{p.name}</div>
        <div className="mt-2 font-display text-4xl font-medium tracking-tight">
          {discounted
            ? <><span className="text-2xl text-muted-foreground line-through mr-2 font-normal">{fmtUsd(p.price_usd)}</span>{fmtUsd(usd)}</>
            : fmtUsd(usd)}
        </div>
        {inr && <div className="text-sm text-muted-foreground mt-0.5">{fmtInr(inr)}</div>}
        <div className="mt-1 text-sm text-muted-foreground">
          {fmtCredits(p.credits)} credits
          {p.bonus_credits > 0 && <span className="text-emerald-400"> + {fmtCredits(p.bonus_credits)} bonus</span>}
        </div>
        <ul className="mt-5 space-y-2 flex-1">
          {p.description && <FeatureItem>{p.description}</FeatureItem>}
          {(p.highlights || []).slice(0, 3).map((h) => (
            <FeatureItem key={h.service_key}>about {fmtCredits(h.units)} &times; {h.description.toLowerCase()}</FeatureItem>
          ))}
          <FeatureItem>Never-expiring credits</FeatureItem>
          <FeatureItem>Works across every IEMA.ai tool</FeatureItem>
        </ul>
        <Button data-testid={BILLING.buyBtn} className="mt-6 w-full" variant={p.is_popular ? 'default' : 'outline'}
          onClick={() => buyPack(p)} disabled={buying === p.slug}>
          {buying === p.slug ? <Loader2 className="h-4 w-4 animate-spin" /> : `Buy ${p.name}`}
        </Button>
      </div>
    );
  };

  return (
    <div className="p-6 md:p-8 max-w-6xl">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-medium tracking-tight">Add credits</h1>
        <p className="text-muted-foreground mt-1">
          One wallet for everything you do in IEMA.ai. Credits never expire. Pay for what you use, no subscription.
        </p>
      </div>

      {loading || !pricing ? (
        <div className="space-y-4">
          <Skeleton className="h-56 rounded-2xl" />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-72 rounded-2xl" />)}
          </div>
        </div>
      ) : (
        <>
          <PaygCard pricing={pricing} />

          <div className="flex items-end justify-between mt-12 mb-4 gap-4 flex-wrap">
            <div>
              <h2 className="font-display text-2xl font-medium">Credit packs</h2>
              <p className="text-sm text-muted-foreground">Bundles of the same credits with bonus value.</p>
            </div>
            <div className="flex items-center gap-2" data-testid="billing-discount">
              <Input placeholder="Discount code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())}
                onKeyDown={(e) => { if (e.key === 'Enter') applyCode(); }} disabled={!!applied}
                className="h-9 w-40 uppercase" />
              {applied ? (
                <Button variant="outline" className="h-9" onClick={clearCode}>Remove</Button>
              ) : (
                <Button variant="outline" className="h-9" onClick={applyCode} disabled={applying || !code.trim()}>
                  {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Apply'}
                </Button>
              )}
            </div>
          </div>
          {applied && <p className="text-sm text-emerald-400 mb-4 -mt-2">Code <span className="font-medium">{applied}</span> applied.</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{general.map(renderPack)}</div>

          {specialised.length > 0 && (
            <>
              <h2 className="font-display text-2xl font-medium mt-12">Specialised packs</h2>
              <p className="text-sm text-muted-foreground mb-4">Credits tuned for one kind of work. They still work everywhere.</p>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="billing-specialised">
                {specialised.map(renderPack)}
              </div>
            </>
          )}
        </>
      )}

      <div className="mt-10 rounded-xl border border-border bg-[hsl(var(--surface))] p-6 flex items-start gap-4">
        <Sparkles className="h-5 w-5 text-primary mt-0.5 flex-shrink-0" />
        <div className="text-sm text-muted-foreground">
          <span className="text-foreground font-medium">Payments powered by Razorpay.</span> Prices are in USD; your card is billed the INR amount shown.
        </div>
      </div>
    </div>
  );
}

function FeatureItem({ children }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <Check className="h-3.5 w-3.5 text-primary flex-shrink-0" />
      <span className="text-muted-foreground">{children}</span>
    </li>
  );
}
