import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  MessagesSquare, Loader2, Sparkles, PlayCircle, History, ChevronRight, Check,
} from 'lucide-react';
import { toast } from 'sonner';
import { setEntitlement } from '@/store/slices/interviewSlice';
import { detailToString, ACTIVE_STATUSES, STATUS_LABEL, TOPIC_META, summarizePackConfig } from './interviewUtils';

export default function InterviewHome() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const entitlement = useSelector((s) => s.interview.entitlement);
  const isAdmin = useSelector((s) => s.auth.user?.role === 'admin');
  const [packs, setPacks] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [buying, setBuying] = useState(null);
  const [fxRate, setFxRate] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [entRes, sessRes] = await Promise.all([
          api.get('/interview/entitlement'),
          api.get('/interview/sessions?limit=20'),
        ]);
        dispatch(setEntitlement(entRes.data));
        setSessions(sessRes.data.items || []);
      } catch (e) {
        toast.error(detailToString(e, 'Failed to load Mock Interviews'));
      } finally {
        setLoading(false);
      }
    })();
    api.get('/interview-packs/?currency=usd').then((r) => setPacks(r.data.items || [])).catch(() => {});
    api.get('/payments/fx-rate').then((r) => setFxRate(r.data.rate)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const inr = (usd) => (fxRate ? `₹${(Math.ceil((usd * fxRate) / 100) * 100).toLocaleString('en-IN')}` : null);

  const activeSession = sessions.find((s) => ACTIVE_STATUSES.includes(s.status));

  const buyRazorpay = async (pack) => {
    setBuying(pack.slug);
    try {
      const { data } = await api.post('/payments/razorpay/order', {
        pack_slug: pack.slug,
        pack_kind: 'interview_sessions',
      });
      if (!data.short_url) {
        toast.error('No checkout URL returned from Razorpay');
        setBuying(null);
        return;
      }
      window.location.href = data.short_url;
    } catch (err) {
      toast.error(detailToString(err, 'Failed to start payment'));
      setBuying(null);
    }
  };

  return (
    <div className="max-w-6xl mx-auto p-6" data-testid="interview-home-page">
      <motion.div
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}
        className="mb-8 flex items-center gap-3"
      >
        <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
          <MessagesSquare className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Mock Interviews</h1>
          <p className="text-sm text-muted-foreground">
            MAANG-style AI mock interviews — 45 min technical + 15 min behavioral, with real proctoring.
          </p>
        </div>
      </motion.div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-40 rounded-2xl" />)}
        </div>
      ) : (
        <div className="space-y-8">
          {/* Entitlement + CTA */}
          <motion.div
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.05 }}
            className="rounded-2xl border border-border bg-card p-6 flex flex-wrap items-center justify-between gap-4"
            data-testid="interview-entitlement-panel"
          >
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">Sessions remaining</div>
              <div className="font-display text-4xl font-semibold mt-1">
                {entitlement.sessionsRemaining ?? 0}
                <span className="text-base text-muted-foreground font-normal"> / {entitlement.sessionsTotal ?? 0}</span>
              </div>
            </div>
            {activeSession ? (
              <Button size="lg" onClick={() => navigate(`/interview/${activeSession.id}`)} data-testid="interview-resume-btn">
                <PlayCircle className="h-4 w-4 mr-2" /> Resume interview
              </Button>
            ) : (
              <div className="flex flex-col items-end gap-1">
                <Button
                  size="lg"
                  onClick={() => navigate('/interview/new')}
                  disabled={!isAdmin && (entitlement.sessionsRemaining ?? 0) <= 0}
                  data-testid="interview-start-btn"
                >
                  <Sparkles className="h-4 w-4 mr-2" /> Start New Interview
                </Button>
                {isAdmin && (entitlement.sessionsRemaining ?? 0) <= 0 && (
                  <span className="text-[11px] text-muted-foreground" data-testid="interview-admin-bypass-note">
                    Admin bypass — no pack required to test
                  </span>
                )}
              </div>
            )}
          </motion.div>

          {/* Paywall / packs */}
          {(entitlement.sessionsRemaining ?? 0) <= 0 && packs.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.1 }}>
              <h2 className="font-display text-xl font-medium mb-4">Get an Interview Pack</h2>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {packs.map((p, i) => (
                  <motion.div
                    key={p.id}
                    initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.1 + i * 0.06 }}
                    className={`relative rounded-2xl border p-6 flex flex-col ${p.is_popular ? 'border-primary shadow-[0_0_30px_hsl(var(--primary)/0.15)]' : 'border-border'} bg-card`}
                    data-testid="interview-pack-card"
                  >
                    {p.is_popular && <Badge className="absolute -top-2 right-4">Most popular</Badge>}
                    <div className="text-sm text-muted-foreground">{p.name}</div>
                    <div className="mt-2 font-display text-4xl font-medium tracking-tight">${p.price.toFixed(2)}</div>
                    {inr(p.price) && <div className="text-sm text-muted-foreground mt-0.5">{inr(p.price)}</div>}
                    <div className="mt-1 text-sm text-muted-foreground">{p.sessions_included} session{p.sessions_included === 1 ? '' : 's'}</div>
                    {p.config && <div className="mt-1 text-xs text-primary/80">{summarizePackConfig(p.config)}</div>}
                    {p.description && <p className="mt-3 text-xs text-muted-foreground flex-1">{p.description}</p>}
                    <ul className="mt-4 space-y-1.5">
                      <li className="flex items-center gap-2 text-xs text-muted-foreground"><Check className="h-3 w-3 text-primary" /> All rounds: DSA / HLD / LLD / Design / HR</li>
                      <li className="flex items-center gap-2 text-xs text-muted-foreground"><Check className="h-3 w-3 text-primary" /> Full proctoring + detailed report</li>
                    </ul>
                    <Button
                      className="mt-6 w-full"
                      variant={p.is_popular ? 'default' : 'outline'}
                      onClick={() => buyRazorpay(p)}
                      disabled={buying === p.slug}
                      data-testid="interview-pack-buy-btn"
                    >
                      {buying === p.slug ? <Loader2 className="h-4 w-4 animate-spin" /> : `Buy ${p.name}`}
                    </Button>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          )}

          {/* Session history */}
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.15 }}>
            <div className="flex items-center gap-1.5 font-medium mb-3">
              <History className="h-4 w-4 text-muted-foreground" /> Session history
            </div>
            {sessions.length === 0 ? (
              <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground" data-testid="interview-history-empty">
                No mock interviews yet — start your first one above.
              </div>
            ) : (
              <div className="rounded-lg border border-border bg-card divide-y divide-border" data-testid="interview-history-list">
                {sessions.map((s, i) => (
                  <motion.button
                    key={s.id}
                    type="button"
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3, delay: i * 0.03 }}
                    onClick={() => navigate(ACTIVE_STATUSES.includes(s.status) ? `/interview/${s.id}` : (s.final_report_id ? `/interview/${s.id}/report` : `/interview/${s.id}`))}
                    className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/50 transition-colors"
                    data-testid={`interview-history-row-${s.id}`}
                  >
                    <Badge variant="outline">{TOPIC_META[s.topic]?.label || s.topic}</Badge>
                    <span className="text-sm flex-1">{STATUS_LABEL[s.status] || s.status}</span>
                    <span className="text-xs text-muted-foreground">{new Date(s.created_at).toLocaleString()}</span>
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  </motion.button>
                ))}
              </div>
            )}
          </motion.div>
        </div>
      )}
    </div>
  );
}
