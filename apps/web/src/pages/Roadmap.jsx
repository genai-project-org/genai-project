import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Loader2, Map as MapIcon, Flame, CheckCircle2, Circle, Info, Building2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

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

const QUESTION_TYPE_LABEL = { code: 'Code', sql: 'SQL', mcq: 'MCQ', design: 'Design' };

// Fallback ordering for a path this frontend doesn't recognize yet — the
// backend is the real source of ordering truth (it already sorts `items`
// and `progress.paths`), this only affects which TAB is selected by default.
const PATH_ORDER_FALLBACK = ['DSA', 'SQL', 'Logical Reasoning', 'Computer Networks', 'System Design'];

export default function Roadmap() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [progress, setProgress] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedCompanies, setSelectedCompanies] = useState([]);
  const [activePath, setActivePath] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [roadmapRes, progressRes] = await Promise.all([
          api.get('/practice/roadmap'),
          api.get('/practice/progress'),
        ]);
        setItems(roadmapRes.data.items || []);
        setProgress(progressRes.data);
      } catch (e) {
        setError(detailToString(e, 'Failed to load roadmap'));
        toast.error(detailToString(e, 'Failed to load roadmap'));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Top-level grouping by `path` (DSA / SQL / Logical Reasoning / Computer
  // Networks / System Design), each holding its own step-grouped view
  // exactly like the original flat DSA-only roadmap did — the backend
  // already sorts `items` by (path, step, order), so grouping here is pure
  // bucketing, never re-sorting.
  const pathGroups = useMemo(() => {
    const out = [];
    const byPath = new Map();
    for (const item of items) {
      if (!byPath.has(item.path)) {
        const bucket = { path: item.path, items: [] };
        byPath.set(item.path, bucket);
        out.push(bucket);
      }
      byPath.get(item.path).items.push(item);
    }
    return out;
  }, [items]);

  useEffect(() => {
    if (!activePath && pathGroups.length > 0) setActivePath(pathGroups[0].path);
  }, [pathGroups, activePath]);

  const stepGroupsForActivePath = useMemo(() => {
    const group = pathGroups.find((g) => g.path === activePath);
    if (!group) return [];
    const out = [];
    const byStep = new Map();
    for (const item of group.items) {
      if (!byStep.has(item.step)) {
        const bucket = { step: item.step, items: [] };
        byStep.set(item.step, bucket);
        out.push(bucket);
      }
      byStep.get(item.step).items.push(item);
    }
    return out;
  }, [pathGroups, activePath]);

  const allCompanies = useMemo(() => {
    const set = new Set();
    for (const item of items) for (const c of item.companies || []) set.add(c);
    return [...set].sort();
  }, [items]);

  const toggleCompany = (c) => {
    setSelectedCompanies((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  };

  // Client-side filter — the roadmap list is small enough (a foundational
  // problem set, not TUF+'s full scale) that there's no need for a
  // server round-trip just to narrow by company tag.
  const visibleStepGroups = useMemo(() => {
    if (selectedCompanies.length === 0) return stepGroupsForActivePath;
    return stepGroupsForActivePath
      .map((g) => ({
        ...g,
        items: g.items.filter((item) => (item.companies || []).some((c) => selectedCompanies.includes(c))),
      }))
      .filter((g) => g.items.length > 0);
  }, [stepGroupsForActivePath, selectedCompanies]);

  const goToProblem = (problemId) => navigate(`/practice?problem=${problemId}`);

  const activePathProgress = useMemo(
    () => (progress?.paths || []).find((p) => p.path === activePath) || null,
    [progress, activePath],
  );

  return (
    <div className="max-w-[1100px] mx-auto p-6" data-testid="roadmap-page">
      <div className="mb-6 flex items-center gap-3">
        <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
          <MapIcon className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Practice Roadmap</h1>
          <p className="text-sm text-muted-foreground">Five structured, topic-ordered problem sheets — track your progress and streak in each.</p>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive" data-testid="roadmap-load-error">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm py-12 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading roadmap…
        </div>
      ) : (
        <>
          {/* Overall progress / streak dashboard — across every path. */}
          {progress && (
            <div className="mb-6 rounded-lg border border-border bg-card p-5" data-testid="roadmap-progress-panel">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div>
                  <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Overall progress</div>
                  <div className="flex items-baseline gap-2 mb-2">
                    <span className="font-display text-2xl font-semibold" data-testid="roadmap-total-solved">
                      {progress.total_solved}
                    </span>
                    <span className="text-sm text-muted-foreground">/ {progress.total_problems} solved</span>
                  </div>
                  <Progress value={progress.overall_pct} />
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Current streak</div>
                  <div className="flex items-center gap-2">
                    <Flame className={cn('h-6 w-6', progress.current_streak_days > 0 ? 'text-orange-500' : 'text-muted-foreground/40')} />
                    <span className="font-display text-2xl font-semibold" data-testid="roadmap-streak">
                      {progress.current_streak_days}
                    </span>
                    <span className="text-sm text-muted-foreground">day{progress.current_streak_days === 1 ? '' : 's'}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-2">Consecutive days with at least one submission, across every path.</p>
                </div>
              </div>
            </div>
          )}

          {/* Top-level path tabs — DSA / SQL / Logical Reasoning / Computer Networks / System Design. */}
          {pathGroups.length > 0 && activePath && (
            <Tabs value={activePath} onValueChange={setActivePath} className="mb-6" data-testid="roadmap-path-tabs">
              <TabsList className="flex-wrap h-auto">
                {pathGroups.map((g) => (
                  <TabsTrigger key={g.path} value={g.path} data-testid={`roadmap-path-tab-${g.path}`}>
                    {g.path}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          )}

          {/* Per-path progress + by-topic breakdown. */}
          {activePathProgress && (
            <div className="mb-6 rounded-lg border border-border bg-card p-5" data-testid={`roadmap-path-progress-${activePath}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-medium">{activePath} progress</div>
                <div className="text-sm text-muted-foreground">
                  {activePathProgress.solved} / {activePathProgress.total} solved
                </div>
              </div>
              <Progress value={activePathProgress.pct} className="mb-3" />
              <div className="space-y-1.5">
                {activePathProgress.steps.map((s) => (
                  <div key={s.step} className="flex items-center gap-2 text-xs" data-testid={`roadmap-step-progress-${s.step}`}>
                    <span className="w-40 truncate text-muted-foreground">{s.step}</span>
                    <Progress value={s.pct} className="h-1.5 flex-1" />
                    <span className="w-10 text-right tabular-nums">{s.solved}/{s.total}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Company filter */}
          {allCompanies.length > 0 && (
            <div className="mb-6 rounded-lg border border-border bg-card p-4" data-testid="roadmap-company-filter">
              <div className="flex items-center gap-1.5 text-sm font-medium mb-2">
                <Building2 className="h-4 w-4 text-muted-foreground" />
                Filter by company
              </div>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {allCompanies.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => toggleCompany(c)}
                    data-testid={`roadmap-company-chip-${c}`}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs transition-colors',
                      selectedCompanies.includes(c)
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background text-muted-foreground border-border hover:bg-accent'
                    )}
                  >
                    {c}
                  </button>
                ))}
                {selectedCompanies.length > 0 && (
                  <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setSelectedCompanies([])} data-testid="roadmap-clear-filter">
                    Clear
                  </Button>
                )}
              </div>
              <div className="flex items-start gap-1.5 text-xs text-muted-foreground/80">
                <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                <span>
                  Company tags are illustrative topic associations, not verified real interview-frequency
                  data — we don't have access to real recruiter/interview records.
                </span>
              </div>
            </div>
          )}

          {/* Step-grouped, ordered problem list for the active path. */}
          <div className="space-y-6" data-testid={`roadmap-path-content-${activePath}`}>
            {visibleStepGroups.map((group) => (
              <div key={group.step} data-testid={`roadmap-step-${group.step}`}>
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-2">{group.step}</h2>
                <div className="rounded-lg border border-border bg-card divide-y divide-border overflow-hidden">
                  {group.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => goToProblem(item.id)}
                      className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/50 transition-colors"
                      data-testid={`roadmap-row-${item.id}`}
                    >
                      {item.solved ? (
                        <CheckCircle2 className="h-4.5 w-4.5 text-emerald-500 shrink-0" data-testid={`roadmap-solved-${item.id}`} />
                      ) : (
                        <Circle className="h-4.5 w-4.5 text-muted-foreground/40 shrink-0" />
                      )}
                      <span className="w-5 text-xs text-muted-foreground tabular-nums shrink-0">{item.order}</span>
                      <span className="flex-1 min-w-0 truncate font-medium text-sm">{item.title}</span>
                      <Badge variant="outline" className="shrink-0 text-[10px]">
                        {QUESTION_TYPE_LABEL[item.question_type] || item.question_type}
                      </Badge>
                      <Badge variant="outline" className={cn('shrink-0', DIFFICULTY_COLOR[item.difficulty] || '')}>
                        {item.difficulty}
                      </Badge>
                      <div className="hidden sm:flex items-center gap-1 shrink-0 max-w-[220px] overflow-hidden">
                        {(item.companies || []).slice(0, 3).map((c) => (
                          <Badge key={c} variant="secondary" className="text-[10px]">{c}</Badge>
                        ))}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {visibleStepGroups.length === 0 && (
              <div className="text-center text-sm text-muted-foreground py-12">
                No problems match the selected company filters.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
