import { useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { fmtCredits, fmtInr, fmtUsd, inrFor } from '@/lib/pricing';

/** Pay-as-you-go recharge. Everything (minimum, presets, credit rate) comes from GET /pricing. */
export default function PaygCard({ pricing }) {
  const payg = pricing.payg;
  const [amount, setAmount] = useState(String(payg.presets[0]?.usd ?? payg.min_usd));
  const [busy, setBusy] = useState(false);

  const value = parseFloat(amount);
  const valid = Number.isFinite(value) && value >= payg.min_usd && value <= payg.max_usd;
  const credits = valid ? Math.floor(value * payg.credits_per_usd) : 0;
  const inr = valid ? inrFor(value, pricing) : null;
  let hint = null;
  if (amount !== '' && Number.isFinite(value)) {
    if (value < payg.min_usd) hint = `Minimum recharge is ${fmtUsd(payg.min_usd)}`;
    else if (value > payg.max_usd) hint = `Maximum recharge is ${fmtUsd(payg.max_usd)}`;
  }

  const pay = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      const { data } = await api.post('/payments/razorpay/payg', { amount_usd: value });
      if (!data.short_url) throw new Error('No checkout URL returned');
      window.location.href = data.short_url; // Razorpay-hosted checkout (rzp.io)
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Failed to start payment');
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-border bg-card p-6" data-testid="billing-payg">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-[260px] flex-1">
          <div className="text-xs uppercase tracking-wider text-primary">Pay as you go</div>
          <h2 className="font-display text-2xl font-medium mt-1">Recharge any amount</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Minimum {fmtUsd(payg.min_usd)}. {fmtCredits(payg.credits_per_usd)} credits per $1, no expiry, no plan needed.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {payg.presets.map((p) => (
              <Button key={p.usd} type="button" size="sm"
                variant={value === p.usd ? 'default' : 'outline'}
                onClick={() => setAmount(String(p.usd))} data-testid={`payg-preset-${p.usd}`}>
                {fmtUsd(p.usd)}
              </Button>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-2">
            <span className="text-muted-foreground">$</span>
            <Input type="number" inputMode="decimal" min={payg.min_usd} max={payg.max_usd} step={payg.step_usd}
              value={amount} onChange={(e) => setAmount(e.target.value)} className="h-10 w-36"
              data-testid="payg-amount" aria-label="Recharge amount in USD" />
          </div>
          {hint && <p className="mt-2 text-sm text-amber-500" data-testid="payg-hint">{hint}</p>}
        </div>

        <div className="min-w-[220px] rounded-xl bg-[hsl(var(--surface))] p-5">
          <div className="text-sm text-muted-foreground">You get</div>
          <div className="font-display text-3xl font-medium mt-1" data-testid="payg-credits">
            {valid ? fmtCredits(credits) : '—'} <span className="text-base font-normal text-muted-foreground">credits</span>
          </div>
          <div className="text-sm text-muted-foreground mt-1">
            {valid ? <>{fmtUsd(value)}{inr ? <> &middot; {fmtInr(inr)} at checkout</> : null}</> : 'Enter an amount to see your credits'}
          </div>
          <Button className="mt-4 w-full" onClick={pay} disabled={!valid || busy} data-testid="payg-pay-btn">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Recharge'}
          </Button>
        </div>
      </div>
    </div>
  );
}
