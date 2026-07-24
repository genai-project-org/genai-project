import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts';
import { BarChart3, Zap, TrendingUp, Activity, Clock, Timer } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

const PERIODS = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7 days' },
  { key: '30d', label: '30 days' },
  { key: '90d', label: '90 days' },
  { key: 'lifetime', label: 'All' },
];

export default function Usage() {
  const [summary, setSummary] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [window, setWindow] = useState(null);
  const [period, setPeriod] = useState('30d');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [s, t, w] = await Promise.all([
          api.get('/usage/summary'),
          api.get(`/usage/timeline?period=${period}`),
          api.get('/wallet/window'),
        ]);
        setSummary(s.data);
        setTimeline(t.data.items);
        setWindow(w.data);
      } finally { setLoading(false); }
    })();
  }, [period]);

  return (
    <div className="p-6 md:p-8 max-w-7xl">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-medium tracking-tight">Usage Analytics</h1>
        <p className="text-muted-foreground mt-1">Track credits and requests. No pricing — just your activity.</p>
      </div>

      {window && <UsageWindow window={window.window} plan={window.plan} />}

      <Tabs value={period} onValueChange={setPeriod} className="mb-6 mt-6">
        <TabsList>
          {PERIODS.map((p) => <TabsTrigger key={p.key} value={p.key}>{p.label}</TabsTrigger>)}
        </TabsList>
      </Tabs>

      {loading || !summary ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">{[...Array(4)].map((_,i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard icon={Zap} label="Today" value={summary.credits_used_today} sub={`${summary.requests_today} requests`} />
            <StatCard icon={TrendingUp} label="This week" value={summary.credits_used_week} sub={`${summary.requests_week} requests`} />
            <StatCard icon={BarChart3} label="This month" value={summary.credits_used_month} sub={`${summary.requests_month} requests`} />
            <StatCard icon={Activity} label="Lifetime" value={summary.credits_used_lifetime} sub={`${summary.requests_lifetime} requests`} />
          </div>

          <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 rounded-xl border border-border bg-card p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-display text-lg font-medium">Credits over time</h3>
                <span className="text-xs text-muted-foreground uppercase tracking-wider">{period}</span>
              </div>
              <div className="h-72">
                <ResponsiveContainer>
                  <LineChart data={timeline}>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
                    <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={11} />
                    <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} />
                    <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }} />
                    <Line type="monotone" dataKey="credits" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card p-6 space-y-4">
              <h3 className="font-display text-lg font-medium">Insights</h3>
              <InfoRow label="Avg credits/request" value={summary.avg_credits_per_request} />
              <InfoRow label="Top provider" value={summary.most_used_provider || '—'} />
              <InfoRow label="Top model" value={summary.most_used_model || '—'} />
              <InfoRow label="Total requests" value={summary.requests_lifetime} />
            </div>
          </div>

          <div className="mt-6 rounded-xl border border-border bg-card p-6">
            <h3 className="font-display text-lg font-medium mb-4">Requests per day</h3>
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={timeline}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
                  <XAxis dataKey="date" stroke="hsl(var(--muted-foreground))" fontSize={11} />
                  <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} />
                  <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }} />
                  <Bar dataKey="requests" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, sub }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5 hover:border-primary/30 transition-colors">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs uppercase tracking-wider text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-primary" strokeWidth={1.75} />
      </div>
      <div className="font-display text-3xl font-medium tracking-tight">{Math.floor(value).toLocaleString()}</div>
      <div className="text-xs text-muted-foreground mt-1">{sub}</div>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div className="flex items-center justify-between text-sm py-1.5 border-b border-border/50 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function UsageWindow({ window, plan }) {
  const used = window?.used || 0;
  const cap = window?.cap || 1;
  const pct = Math.min(100, Math.round((used / cap) * 100));
  const [remaining, setRemaining] = useState('');
  useEffect(() => {
    if (!window?.resets_at) return;
    const tick = () => {
      const ms = Math.max(0, new Date(window.resets_at) - new Date());
      const h = Math.floor(ms / 3.6e6);
      const m = Math.floor((ms % 3.6e6) / 60000);
      setRemaining(`${h}h ${m}m`);
    };
    tick();
    const id = setInterval(tick, 30000);
    return () => clearInterval(id);
  }, [window]);
  const critical = pct >= 90;
  return (
    <div className="rounded-xl border border-border bg-card p-5" data-testid="usage-window-widget">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Timer className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">Current window</span>
          <span className="text-xs text-muted-foreground uppercase tracking-wider">· {plan?.name || plan?.plan_id}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" /> resets in <span className="text-foreground font-medium">{remaining || '—'}</span>
        </div>
      </div>
      <div className="w-full h-2 rounded-full bg-[hsl(var(--surface))] overflow-hidden">
        <div className={cn('h-full rounded-full transition-all duration-500', critical ? 'bg-red-500' : 'bg-primary')} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{Math.floor(used)} / {Math.floor(cap)} used</span>
        <span className={cn('text-muted-foreground', critical && 'text-red-500 font-medium')}>{Math.max(0, Math.floor(cap - used))} remaining</span>
      </div>
    </div>
  );
}
