import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '@/lib/api';
import { Wallet as WalletIcon, ArrowUpRight, Gift, Sparkles, Users, ShoppingCart, TrendingDown } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { format } from 'date-fns';
import { WALLET } from '@/constants/testIds';

export default function Wallet() {
  const [wallet, setWallet] = useState(null);
  const [txs, setTxs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [w, t] = await Promise.all([api.get('/wallet/'), api.get('/wallet/transactions')]);
        setWallet(w.data);
        setTxs(t.data.items);
      } finally { setLoading(false); }
    })();
  }, []);

  const buckets = wallet ? [
    { key: 'welcome', label: 'Welcome', value: wallet.welcome_credits, Icon: Gift, color: 'text-primary' },
    { key: 'daily', label: 'Daily', value: wallet.daily_credits, Icon: Sparkles, color: 'text-primary' },
    { key: 'bonus', label: 'Bonus', value: wallet.bonus_credits, Icon: Gift, color: 'text-purple-400' },
    { key: 'referral', label: 'Referral', value: wallet.referral_credits, Icon: Users, color: 'text-emerald-400' },
    { key: 'purchased', label: 'Purchased', value: wallet.purchased_credits, Icon: ShoppingCart, color: 'text-primary' },
  ] : [];

  return (
    <div className="p-6 md:p-8 max-w-6xl">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-medium tracking-tight">Credit Wallet</h1>
        <p className="text-muted-foreground mt-1">All your credits, organized by source.</p>
      </div>

      {loading || !wallet ? (
        <Skeleton className="h-40 rounded-xl mb-6" />
      ) : (
        <div className="rounded-2xl border border-border bg-card relative overflow-hidden mb-8">
          <div className="spot-glow" />
          <div className="relative p-8 flex flex-col sm:flex-row items-start sm:items-end justify-between gap-6">
            <div>
              <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground mb-2">
                <WalletIcon className="h-3.5 w-3.5" /> Total balance
              </div>
              <div data-testid={WALLET.totalCredits} className="font-display text-5xl md:text-6xl font-medium tracking-tighter">
                {Math.floor(wallet.total).toLocaleString()}
              </div>
              <div className="text-sm text-muted-foreground mt-1">credits available</div>
            </div>
            <Link to="/billing">
              <Button size="lg" className="rounded-full" data-testid={WALLET.rechargeBtn}>
                Recharge <ArrowUpRight className="h-4 w-4 ml-1" />
              </Button>
            </Link>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-8">
        {buckets.map(({ key, label, value, Icon, color }) => (
          <div key={key} className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-2">
              <Icon className={`h-4 w-4 ${color}`} strokeWidth={1.75} />
              <span className="text-xs uppercase tracking-wider text-muted-foreground">{label}</span>
            </div>
            <div className="font-display text-xl font-medium">{Math.floor(value).toLocaleString()}</div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-5 py-4 border-b border-border">
          <h3 className="font-display text-lg font-medium">Recent transactions</h3>
        </div>
        {txs.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-sm">No transactions yet</div>
        ) : (
          <div className="divide-y divide-border">
            {txs.map((tx) => (
              <div key={tx.id} className="px-5 py-3 flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  <div className={`h-8 w-8 rounded-md flex items-center justify-center ${tx.amount > 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-destructive/10 text-destructive'}`}>
                    {tx.amount > 0 ? <ArrowUpRight className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{tx.description || tx.kind}</div>
                    <div className="text-xs text-muted-foreground">{tx.created_at ? format(new Date(tx.created_at), 'PP p') : ''}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Badge variant="secondary" className="text-xs">{tx.bucket}</Badge>
                  <div className={`font-mono text-sm ${tx.amount > 0 ? 'text-emerald-400' : 'text-destructive'}`}>
                    {tx.amount > 0 ? '+' : ''}{Math.floor(tx.amount)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
