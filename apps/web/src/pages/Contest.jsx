import { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Loader2, Trophy, Users, Clock, Download, Award, Code2, ShieldCheck, Pencil, Octagon,
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import ContestAdminPanel from '@/components/contest/ContestAdminPanel';
import ContestLanding from '@/components/contest/ContestLanding';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog';

// Same flattening trick Practice.jsx/Roadmap.jsx use — FastAPI's 402/429
// responses carry structured `detail` objects, everything else a plain string.
function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

const DIFFICULTY_COLOR = {
  Easy: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  Medium: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  Hard: 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30',
};

const STATUS_BADGE = {
  upcoming: 'bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30',
  live: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  ended: 'bg-muted text-muted-foreground border-border',
};

function fmtDuration(ms) {
  if (ms <= 0) return '0s';
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

async function downloadBlob(path, filename) {
  const { data } = await api.get(path, { responseType: 'blob' });
  const blobUrl = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(blobUrl);
}

export default function Contest() {
  const navigate = useNavigate();
  const user = useSelector((s) => s.auth.user);
  const [contests, setContests] = useState([]);
  const [contestId, setContestId] = useState(null);
  const [contest, setContest] = useState(null);
  const [leaderboard, setLeaderboard] = useState(null);
  const [myStats, setMyStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => Date.now());

  // Admin: create/edit contest panel. 'create' | 'edit' | null.
  const [adminPanelMode, setAdminPanelMode] = useState(null);

  const [downloading, setDownloading] = useState(null); // 'certificate' | 'stats-card' | null
  const [stopping, setStopping] = useState(false);

  // Tick every second for the live countdown.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError('');
      try {
        const { data } = await api.get('/contest/');
        setContests(data.items || []);
        if (data.items?.length) {
          // Prefer a live contest, else the most recently created one (the
          // backend already sorts newest-first).
          const live = data.items.find((c) => c.status === 'live');
          setContestId((live || data.items[0]).id);
        } else {
          setLoading(false);
        }
      } catch (e) {
        setError(detailToString(e, 'Failed to load contests'));
        setLoading(false);
      }
    })();
  }, []);

  const loadContestData = async (id) => {
    if (!id) return;
    setLoading(true);
    setError('');
    try {
      const [detailRes, lbRes, statsRes] = await Promise.all([
        api.get(`/contest/${id}`),
        api.get(`/contest/${id}/leaderboard`),
        api.get(`/contest/${id}/my-stats`),
      ]);
      setContest(detailRes.data);
      setLeaderboard(lbRes.data);
      setMyStats(statsRes.data);
    } catch (e) {
      setError(detailToString(e, 'Failed to load contest'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (contestId) loadContestData(contestId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contestId]);

  const windowInfo = useMemo(() => {
    if (!contest) return null;
    const start = new Date(contest.start_at).getTime();
    const end = new Date(contest.end_at).getTime();
    if (now < start) return { label: 'Starts in', ms: start - now, status: 'upcoming' };
    if (now > end) return { label: 'Ended', ms: 0, status: 'ended' };
    return { label: 'Ends in', ms: end - now, status: 'live' };
  }, [contest, now]);


  const onContestSaved = async (savedId) => {
    setAdminPanelMode(null);
    const { data: listData } = await api.get('/contest/');
    setContests(listData.items || []);
    if (savedId === contestId) {
      await loadContestData(savedId);
    } else {
      setContestId(savedId);
    }
  };

  const stopContestNow = async () => {
    if (stopping) return;
    setStopping(true);
    try {
      await api.post(`/contest/${contestId}/stop`);
      toast.success('Contest stopped — submissions are closed immediately.');
      await loadContestData(contestId);
    } catch (e) {
      toast.error(detailToString(e, 'Failed to stop contest'));
    } finally {
      setStopping(false);
    }
  };

  const download = async (kind) => {
    if (downloading) return;
    setDownloading(kind);
    try {
      const filename = kind === 'certificate' ? `certificate-${contestId}.pdf` : `stats-card-${contestId}.png`;
      await downloadBlob(`/contest/${contestId}/${kind}`, filename);
      toast.success(kind === 'certificate' ? 'Certificate downloaded' : 'Stats card downloaded');
    } catch (e) {
      toast.error(detailToString(e, 'Download failed — make a contest submission first'));
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="max-w-[1100px] mx-auto p-6" data-testid="contest-page">
      <div className="mb-6 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Trophy className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Hackathon Contest Mode</h1>
            <p className="text-sm text-muted-foreground">Free-entry, team-based, timed coding contest — built on the Practice Engine.</p>
          </div>
        </div>
        {user?.role === 'admin' && (
          <div className="flex items-center gap-2">
            {contest && (
              <Button
                variant="outline" size="sm"
                onClick={() => setAdminPanelMode((v) => (v === 'edit' ? null : 'edit'))}
                data-testid="contest-admin-edit-toggle"
              >
                <Pencil className="h-4 w-4 mr-2" /> {adminPanelMode === 'edit' ? 'Close' : 'Edit Contest'}
              </Button>
            )}
            {contest && contest.status !== 'ended' && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="destructive" size="sm" data-testid="contest-stop-btn">
                    <Octagon className="h-4 w-4 mr-2" /> Stop Contest
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Stop "{contest.name}" now?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This immediately ends the contest for every participant, regardless of its scheduled end
                      time — submissions are rejected right away and this cannot be undone.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel data-testid="contest-stop-cancel">Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={stopContestNow}
                      disabled={stopping}
                      className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      data-testid="contest-stop-confirm"
                    >
                      {stopping ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                      Stop contest now
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            <Button
              variant="outline" size="sm"
              onClick={() => setAdminPanelMode((v) => (v === 'create' ? null : 'create'))}
              data-testid="contest-admin-toggle"
            >
              <ShieldCheck className="h-4 w-4 mr-2" /> {adminPanelMode === 'create' ? 'Close' : 'New Contest'}
            </Button>
          </div>
        )}
      </div>

      {/* Non-admins get no admin UI at all — not even a disabled button — the backend's
          403 is real defense-in-depth, this is the UI-level gate the task calls for. */}
      {user?.role === 'admin' && adminPanelMode === 'create' && (
        <ContestAdminPanel editingContest={null} onSaved={onContestSaved} onClose={() => setAdminPanelMode(null)} />
      )}
      {user?.role === 'admin' && adminPanelMode === 'edit' && contest && (
        <ContestAdminPanel editingContest={contest} onSaved={onContestSaved} onClose={() => setAdminPanelMode(null)} />
      )}

      {contests.length > 1 && (
        <div className="mb-4 flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Contest:</span>
          <Select value={contestId ?? undefined} onValueChange={setContestId}>
            <SelectTrigger className="w-72" data-testid="contest-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {contests.map((c) => (
                <SelectItem key={c.id} value={c.id}>{c.name} ({c.status})</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive" data-testid="contest-error">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-muted-foreground text-sm py-12 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading contest…
        </div>
      )}

      {!loading && contests.length === 0 && !error && (
        <div className="text-center text-sm text-muted-foreground py-12" data-testid="contest-empty">
          No contests are running right now. Check back soon.
        </div>
      )}

      {/* Not-yet-registered visitor: the auto-generated registration landing
          page is the default view. Once they're on a team, they fall through
          to the dashboard below instead. */}
      {!loading && contest && !contest.my_team && (
        <ContestLanding contest={contest} userName={user?.name} onRegistered={() => loadContestData(contestId)} />
      )}

      {!loading && contest && contest.my_team && (
        <div className="space-y-6">
          {/* Window status */}
          <div className="rounded-lg border border-border bg-card p-5 flex flex-wrap items-center justify-between gap-4" data-testid="contest-window-panel">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h2 className="text-xl font-semibold">{contest.name}</h2>
                <Badge variant="outline" className={STATUS_BADGE[contest.status] || ''}>{contest.status}</Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {new Date(contest.start_at).toLocaleString()} &rarr; {new Date(contest.end_at).toLocaleString()}
              </p>
            </div>
            <div className="flex items-center gap-2 text-lg font-display font-semibold" data-testid="contest-countdown">
              <Clock className="h-5 w-5 text-primary" />
              {windowInfo?.status === 'ended' ? 'Contest has ended' : `${windowInfo?.label}: ${fmtDuration(windowInfo?.ms || 0)}`}
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Problems */}
            <div className="rounded-lg border border-border bg-card p-5" data-testid="contest-problems">
              <div className="flex items-center gap-1.5 font-medium mb-3">
                <Code2 className="h-4 w-4 text-muted-foreground" /> Problem set
              </div>
              <div className="space-y-2">
                {contest.problems.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => navigate(`/practice?problem=${p.id}`)}
                    className="w-full flex items-center gap-3 rounded-md border border-border px-3 py-2 text-left hover:bg-accent/50 transition-colors"
                    data-testid={`contest-problem-${p.id}`}
                  >
                    <span className="flex-1 text-sm font-medium">{p.title}</span>
                    <Badge variant="outline" className={DIFFICULTY_COLOR[p.difficulty] || ''}>{p.difficulty}</Badge>
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-3">
                Solve in the real Practice Engine editor, then submit there while this contest is live — contest submissions are free (no credits charged).
              </p>
            </div>

            {/* Team */}
            <div className="rounded-lg border border-border bg-card p-5" data-testid="contest-team-panel">
              <div className="flex items-center gap-1.5 font-medium mb-3">
                <Users className="h-4 w-4 text-muted-foreground" /> Your team
              </div>
              {/* This dashboard only ever renders once contest.my_team exists —
                  see the landing-vs-dashboard branch above — so there is no
                  "create a team" form here any more; that's ContestLanding's job. */}
              <div data-testid="contest-my-team">
                <div className="text-lg font-semibold mb-1">{contest.my_team.name}</div>
                <div className="text-xs text-muted-foreground">{contest.my_team.member_user_ids.length} member(s)</div>
              </div>
            </div>
          </div>

          {/* Leaderboard */}
          <div className="rounded-lg border border-border bg-card p-5" data-testid="contest-leaderboard">
            <div className="flex items-center gap-1.5 font-medium mb-3">
              <Trophy className="h-4 w-4 text-amber-500" /> Leaderboard
            </div>
            {!leaderboard?.items?.length ? (
              <p className="text-sm text-muted-foreground py-6 text-center">No team has solved a problem yet.</p>
            ) : (
              <div className="divide-y divide-border">
                {leaderboard.items.map((row) => (
                  <div
                    key={row.team_id}
                    className={cn(
                      'flex items-center gap-3 py-2.5 text-sm',
                      row.rank <= 5 && 'font-medium'
                    )}
                    data-testid={`contest-leaderboard-row-${row.rank}`}
                  >
                    <span className={cn('w-8 tabular-nums', row.rank <= 5 ? 'text-primary' : 'text-muted-foreground')}>
                      #{row.rank}
                    </span>
                    <span className="flex-1 truncate">{row.team_name}</span>
                    <span className="text-xs text-muted-foreground hidden sm:inline">
                      {row.members.map((m) => m.name).join(', ')}
                    </span>
                    <Badge variant="secondary" className="shrink-0">{row.problems_solved} solved</Badge>
                    <span className="w-16 text-right text-xs text-muted-foreground tabular-nums shrink-0">
                      {Math.floor(row.total_time_seconds / 60)}m
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground mt-3">
              Ranked by distinct problems solved by the team, tie-broken by total time-to-solve — full standings, visible to every participant.
            </p>
          </div>

          {/* Certificate + stats card */}
          {myStats?.has_participated && (
            <div className="rounded-lg border border-border bg-card p-5 flex flex-wrap items-center justify-between gap-4" data-testid="contest-downloads">
              <div>
                <div className="flex items-center gap-1.5 font-medium mb-1">
                  <Award className="h-4 w-4 text-primary" /> Your contest stats
                </div>
                <p className="text-xs text-muted-foreground">
                  {myStats.problems_solved}/{myStats.total_contest_problems} solved
                  {myStats.team_rank ? ` · Team rank #${myStats.team_rank}` : ''}
                  {myStats.strongest_topic && myStats.strongest_topic !== 'N/A' ? ` · Strongest topic: ${myStats.strongest_topic}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => download('certificate')} disabled={downloading !== null} data-testid="contest-download-certificate">
                  {downloading === 'certificate' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Download className="h-4 w-4 mr-2" />}
                  Certificate (PDF)
                </Button>
                <Button variant="outline" size="sm" onClick={() => download('stats-card')} disabled={downloading !== null} data-testid="contest-download-stats-card">
                  {downloading === 'stats-card' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Download className="h-4 w-4 mr-2" />}
                  Stats card (PNG)
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
