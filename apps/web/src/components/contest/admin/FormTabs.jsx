import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react';
import {
  Field, NumField, ToggleField, SelectField, Section, isoToLocalInput, localToIso,
} from './shared';

const DIFFICULTY_COLOR = {
  Easy: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  Medium: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  Hard: 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30',
};
const LANGS = ['python', 'javascript', 'cpp', 'java'];

// ---------------------------------------------------------------------------
// Overview: name, schedule, publish state
// ---------------------------------------------------------------------------
export function OverviewForm({ form, setForm }) {
  return (
    <div className="space-y-4" data-testid="contest-tab-overview-form">
      <Field label="Contest name">
        <Input placeholder="Contest name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="contest-new-name" />
      </Field>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Start time">
          <Input type="datetime-local" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} data-testid="contest-new-start" />
        </Field>
        <Field label="End time">
          <Input type="datetime-local" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} data-testid="contest-new-end" />
        </Field>
        <SelectField
          label="State" value={form.state} onChange={(v) => setForm({ ...form, state: v })} testid="contest-new-state"
          options={[['published', 'Published (visible to everyone)'], ['draft', 'Draft (admins only)']]}
          hint="Drafts are invisible to participants."
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Problems: pick from the bank, order, per-problem rules
// ---------------------------------------------------------------------------
function ProblemEditor({ p, onChange }) {
  const c = p.config;
  const set = (k, v) => onChange({ ...p, config: { ...c, [k]: v } });
  const toggleLang = (l) => {
    const cur = c.allowed_languages || LANGS;
    const next = cur.includes(l) ? cur.filter((x) => x !== l) : [...cur, l];
    set('allowed_languages', next.length === LANGS.length || next.length === 0 ? null : next);
  };
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-3 border-t border-border bg-muted/30">
      <NumField label="Points" value={c.points} onChange={(v) => set('points', v)} testid={`problem-points-${p.id}`} />
      <NumField label="Time limit (ms)" nullable value={c.time_limit_ms} onChange={(v) => set('time_limit_ms', v)} placeholder="default" min={100} />
      <NumField label="Memory limit (MB)" nullable value={c.memory_limit_mb} onChange={(v) => set('memory_limit_mb', v)} placeholder="default" min={16} />
      <NumField label="Max attempts" nullable value={c.max_attempts} onChange={(v) => set('max_attempts', v)} placeholder="contest default" hint="0 = unlimited" />
      <NumField label="Unlock N min after start" nullable value={c.release_after_minutes} onChange={(v) => set('release_after_minutes', v)} placeholder="at start" testid={`problem-release-min-${p.id}`} />
      <Field label="Or unlock at (exact time)">
        <Input type="datetime-local" value={isoToLocalInput(c.release_at)} onChange={(e) => set('release_at', localToIso(e.target.value))} />
      </Field>
      <NumField label="First-solve bonus" nullable value={c.first_solve_bonus} onChange={(v) => set('first_solve_bonus', v)} placeholder="contest default" />
      <NumField label="Speed bonus max" nullable value={c.speed_bonus_max} onChange={(v) => set('speed_bonus_max', v)} placeholder="contest default" />
      <Field label="Test weights" hint="Comma list by test index, e.g. 1,1,3 (partial credit)" className="col-span-2">
        <Input value={p._weights ?? ''} placeholder="all equal" onChange={(e) => onChange({ ...p, _weights: e.target.value })} />
      </Field>
      <Field label="Visible tests" hint="Indices shown in full, e.g. 0,1 (blank = samples only)" className="col-span-2">
        <Input value={p._visible ?? ''} placeholder="samples only" onChange={(e) => onChange({ ...p, _visible: e.target.value })} />
      </Field>
      <div className="col-span-2 md:col-span-3">
        <Label2>Allowed languages</Label2>
        <div className="flex flex-wrap gap-3">
          {LANGS.map((l) => (
            <label key={l} className="flex items-center gap-1.5 text-xs">
              <Checkbox checked={(c.allowed_languages || LANGS).includes(l)} onCheckedChange={() => toggleLang(l)} /> {l}
            </label>
          ))}
        </div>
      </div>
      <ToggleField label="Hidden" hint="Not shown to participants" checked={c.hidden} onChange={(v) => set('hidden', v)} />
    </div>
  );
}

function Label2({ children }) {
  return <div className="text-xs text-muted-foreground mb-1">{children}</div>;
}

export function ProblemsForm({ form, setForm, bank, isLive }) {
  const [open, setOpen] = useState(null);
  const [q, setQ] = useState('');
  const chosen = new Set(form.problems.map((p) => p.id));
  const available = useMemo(
    () => bank.filter((b) => !chosen.has(b.id) && `${b.title} ${b.step}`.toLowerCase().includes(q.toLowerCase())),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bank, q, form.problems],
  );
  const move = (i, d) => {
    const arr = [...form.problems];
    const j = i + d;
    if (j < 0 || j >= arr.length) return;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    setForm({ ...form, problems: arr });
  };
  const add = (b) => {
    const pts = b.difficulty === 'Hard' ? 200 : b.difficulty === 'Medium' ? 100 : 50;
    setForm({
      ...form,
      problems: [...form.problems, {
        id: b.id, title: b.title, difficulty: b.difficulty,
        config: { points: pts, time_limit_ms: null, memory_limit_mb: null, allowed_languages: null, test_weights: null, visible_tests: null, release_at: null, release_after_minutes: null, max_attempts: null, first_solve_bonus: null, speed_bonus_max: null, hidden: false },
      }],
    });
  };
  return (
    <div className="space-y-4" data-testid="contest-tab-problems-form">
      {isLive && (
        <p className="text-xs rounded-md border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300 px-3 py-2">
          This contest is live. Problem changes apply to everyone as soon as you save, and standings are recomputed from the existing submissions.
        </p>
      )}
      <Section title={`Contest problems (${form.problems.length})`} hint="Order here is the order participants see. Expand a problem for points, limits, unlock time and bonuses.">
        {form.problems.length === 0 && <p className="text-xs text-muted-foreground">No problems yet — add some from the bank below.</p>}
        <div className="space-y-2">
          {form.problems.map((p, i) => (
            <div key={p.id} className="rounded-md border border-border" data-testid={`contest-problem-row-${p.id}`}>
              <div className="flex items-center gap-2 px-3 py-2">
                <button type="button" onClick={() => setOpen(open === p.id ? null : p.id)} className="text-muted-foreground">
                  {open === p.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </button>
                <span className="text-xs text-muted-foreground w-5">{i + 1}.</span>
                <span className="flex-1 text-sm truncate">{p.title}</span>
                {p.config.hidden && <Badge variant="secondary">hidden</Badge>}
                {(p.config.release_after_minutes || p.config.release_at) && <Badge variant="secondary">staged</Badge>}
                <Badge variant="outline" className={DIFFICULTY_COLOR[p.difficulty] || ''}>{p.difficulty}</Badge>
                <span className="text-xs tabular-nums w-14 text-right">{p.config.points} pts</span>
                <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => move(i, -1)} disabled={i === 0}><ArrowUp className="h-3.5 w-3.5" /></Button>
                <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => move(i, 1)} disabled={i === form.problems.length - 1}><ArrowDown className="h-3.5 w-3.5" /></Button>
                <Button type="button" variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setForm({ ...form, problems: form.problems.filter((x) => x.id !== p.id) })} data-testid={`contest-problem-remove-${p.id}`}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
              {open === p.id && <ProblemEditor p={p} onChange={(np) => setForm({ ...form, problems: form.problems.map((x) => (x.id === p.id ? np : x)) })} />}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Problem bank">
        <Input placeholder="Search problems or topics" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="max-h-64 overflow-y-auto rounded-md border border-border divide-y divide-border" data-testid="contest-problem-picker">
          {available.map((b) => (
            <div key={b.id} className="flex items-center gap-2 px-3 py-1.5" data-testid={`contest-problem-picker-item-${b.id}`}>
              <span className="flex-1 text-sm truncate">{b.title}</span>
              <span className="text-[11px] text-muted-foreground hidden sm:inline">{b.step}</span>
              <Badge variant="outline" className={DIFFICULTY_COLOR[b.difficulty] || ''}>{b.difficulty}</Badge>
              <Button type="button" size="sm" variant="outline" className="h-7" onClick={() => add(b)} data-testid={`contest-problem-add-${b.id}`}>
                <Plus className="h-3.5 w-3.5 mr-1" /> Add
              </Button>
            </div>
          ))}
          {available.length === 0 && <p className="text-xs text-muted-foreground p-3 text-center">No more matching problems.</p>}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scoring rules
// ---------------------------------------------------------------------------
const TIE_OPTIONS = [
  ['time', 'Lower total time / penalty'], ['solved', 'More problems solved'], ['last_solve', 'Earlier last solve'],
  ['score', 'Higher score'], ['registered', 'Earlier registration'],
];

export function ScoringForm({ form, setForm }) {
  const sc = form.settings.scoring;
  const set = (k, v) => setForm({ ...form, settings: { ...form.settings, scoring: { ...sc, [k]: v } } });
  const setMile = (i, k, v) => set('milestone_bonuses', sc.milestone_bonuses.map((m, j) => (j === i ? { ...m, [k]: v } : m)));
  const toggleTie = (k) => set('tie_breakers', sc.tie_breakers.includes(k) ? sc.tie_breakers.filter((x) => x !== k) : [...sc.tie_breakers, k]);
  return (
    <div className="space-y-4" data-testid="contest-tab-scoring-form">
      <Section title="Ranking mode">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <SelectField label="Scoring mode" value={sc.mode} onChange={(v) => set('mode', v)} testid="scoring-mode"
            options={[['icpc', 'ICPC — most solved, then least penalty'], ['points', 'Points — highest score']]} />
          <NumField label="Penalty minutes per wrong submission" value={sc.penalty_minutes_per_wrong} onChange={(v) => set('penalty_minutes_per_wrong', v)} hint="ICPC: added to the time of a solved problem" testid="scoring-penalty-min" />
          <NumField label="Max attempts per problem" value={sc.max_attempts} onChange={(v) => set('max_attempts', v)} hint="0 = unlimited. Problems can override." />
        </div>
        <ToggleField label="Partial scoring" hint="Per-test weights give partial credit in points mode" checked={sc.partial_scoring} onChange={(v) => set('partial_scoring', v)} />
      </Section>
      <Section title="Bonuses & negative marking" hint="Applied to the score (and the ranking in points mode).">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <NumField label="Wrong-submission penalty (points)" value={sc.wrong_penalty_points} onChange={(v) => set('wrong_penalty_points', v)} testid="scoring-wrong-points" />
          <NumField label="First-solve bonus" value={sc.first_solve_bonus} onChange={(v) => set('first_solve_bonus', v)} />
          <NumField label="Speed bonus (max)" value={sc.speed_bonus_max} onChange={(v) => set('speed_bonus_max', v)} hint="Decays linearly to 0" />
          <NumField label="Speed decay window (min)" value={sc.speed_bonus_decay_minutes} onChange={(v) => set('speed_bonus_decay_minutes', v)} hint="0 = whole contest" />
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label2>Milestone bonuses</Label2>
            <Button type="button" size="sm" variant="outline" className="h-7" onClick={() => set('milestone_bonuses', [...sc.milestone_bonuses, { solved: 3, points: 25 }])}>
              <Plus className="h-3.5 w-3.5 mr-1" /> Add milestone
            </Button>
          </div>
          {sc.milestone_bonuses.map((m, i) => (
            <div key={i} className="flex items-center gap-2 text-sm">
              Solve
              <Input type="number" className="w-20" min={1} value={m.solved} onChange={(e) => setMile(i, 'solved', Number(e.target.value))} />
              problems, earn +
              <Input type="number" className="w-24" value={m.points} onChange={(e) => setMile(i, 'points', Number(e.target.value))} />
              points
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => set('milestone_bonuses', sc.milestone_bonuses.filter((_, j) => j !== i))}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Grace marks (every participating team)" hint="Per-team manual adjustments live under Participants after the contest is created.">
        <div className="grid grid-cols-2 gap-3">
          <NumField label="Global grace points" value={sc.global_grace_points} onChange={(v) => set('global_grace_points', v)} min={-100000} />
          <NumField label="Global grace minutes (off penalty)" value={sc.global_grace_minutes} onChange={(v) => set('global_grace_minutes', v)} />
        </div>
      </Section>
      <Section title="Tie-breakers" hint="Checked in this order after the primary ranking; then registration time.">
        <div className="flex flex-wrap gap-4">
          {TIE_OPTIONS.map(([k, l]) => (
            <label key={k} className="flex items-center gap-1.5 text-xs">
              <Checkbox checked={sc.tie_breakers.includes(k)} onCheckedChange={() => toggleTie(k)} />
              {l}{sc.tie_breakers.includes(k) ? ` (#${sc.tie_breakers.indexOf(k) + 1})` : ''}
            </label>
          ))}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Leaderboard visibility rules
// ---------------------------------------------------------------------------
export function LeaderboardForm({ form, setForm }) {
  const lb = form.settings.leaderboard;
  const set = (k, v) => setForm({ ...form, settings: { ...form.settings, leaderboard: { ...lb, [k]: v } } });
  return (
    <Section title="Visibility & freeze">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <SelectField label="Leaderboard" value={lb.visibility} onChange={(v) => set('visibility', v)} testid="lb-visibility"
          options={[['visible', 'Visible to participants'], ['after_end', 'Hidden until the contest ends'], ['hidden', 'Hidden (admins only)']]} />
        <NumField label="Freeze in last N minutes" value={lb.freeze_minutes} onChange={(v) => set('freeze_minutes', v)} hint="0 = never freeze" testid="lb-freeze" />
        <ToggleField label="Reveal automatically at end" hint="Off = stays frozen until you reveal" checked={lb.unfreeze_at_end} onChange={(v) => set('unfreeze_at_end', v)} />
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Settings: registration, branding, prizes, certificate
// ---------------------------------------------------------------------------
export function SettingsForm({ form, setForm }) {
  const s = form.settings;
  const setGroup = (g, k, v) => setForm({ ...form, settings: { ...s, [g]: { ...s[g], [k]: v } } });
  const reg = s.registration;
  const setPrize = (i, k, v) => setForm({ ...form, settings: { ...s, prizes: s.prizes.map((p, j) => (j === i ? { ...p, [k]: v } : p)) } });
  return (
    <div className="space-y-4" data-testid="contest-tab-settings-form">
      <Section title="Registration">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <ToggleField label="Registration open" checked={reg.open} onChange={(v) => setGroup('registration', 'open', v)} testid="reg-open" />
          <Field label="Opens at (optional)"><Input type="datetime-local" value={isoToLocalInput(reg.open_at)} onChange={(e) => setGroup('registration', 'open_at', localToIso(e.target.value))} /></Field>
          <Field label="Closes at (optional)"><Input type="datetime-local" value={isoToLocalInput(reg.close_at)} onChange={(e) => setGroup('registration', 'close_at', localToIso(e.target.value))} /></Field>
          <NumField label="Participant cap" value={reg.cap} onChange={(v) => setGroup('registration', 'cap', v)} hint="0 = unlimited" testid="reg-cap" />
          <SelectField label="Participation" value={reg.mode} onChange={(v) => setGroup('registration', 'mode', v)} testid="reg-mode"
            options={[['both', 'Solo or team'], ['solo', 'Solo only'], ['team', 'Teams only']]} />
          <div className="grid grid-cols-2 gap-2">
            <NumField label="Min team" min={1} value={reg.min_team_size} onChange={(v) => setGroup('registration', 'min_team_size', v)} />
            <NumField label="Max team" min={1} value={reg.max_team_size} onChange={(v) => setGroup('registration', 'max_team_size', v)} testid="reg-max-team" />
          </div>
          <SelectField label="Access" value={reg.access} onChange={(v) => setGroup('registration', 'access', v)} testid="reg-access"
            options={[['public', 'Public — anyone can register'], ['invite_only', 'Invite-only (email list)'], ['code', 'Access code']]} />
          {reg.access === 'code' && (
            <Field label="Access code"><Input value={reg.access_code || ''} onChange={(e) => setGroup('registration', 'access_code', e.target.value)} data-testid="reg-code" /></Field>
          )}
        </div>
      </Section>
      <Section title="Branding & rules">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Landing headline (optional)"><Input value={s.branding.headline} onChange={(e) => setGroup('branding', 'headline', e.target.value)} /></Field>
          <Field label="Landing tagline (optional)"><Input value={s.branding.tagline} onChange={(e) => setGroup('branding', 'tagline', e.target.value)} /></Field>
          <Field label="Banner image URL (https)" className="sm:col-span-2"><Input value={s.branding.banner_url || ''} placeholder="https://..." onChange={(e) => setGroup('branding', 'banner_url', e.target.value)} /></Field>
        </div>
        <Field label="Description"><Textarea rows={2} value={s.branding.description} onChange={(e) => setGroup('branding', 'description', e.target.value)} /></Field>
        <Field label="Rules"><Textarea rows={5} value={s.branding.rules_text} onChange={(e) => setGroup('branding', 'rules_text', e.target.value)} data-testid="branding-rules" /></Field>
      </Section>
      <Section title="Prize tiers">
        {s.prizes.map((p, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <NumField label="From rank" min={1} value={p.from_rank} onChange={(v) => setPrize(i, 'from_rank', v)} />
            <NumField label="To rank" min={1} value={p.to_rank} onChange={(v) => setPrize(i, 'to_rank', v)} />
            <Field label="Title"><Input value={p.title} onChange={(e) => setPrize(i, 'title', e.target.value)} /></Field>
            <Field label="Prize"><Input value={p.prize} onChange={(e) => setPrize(i, 'prize', e.target.value)} /></Field>
            <Button type="button" variant="ghost" size="icon" className="h-9 w-9 text-destructive" onClick={() => setForm({ ...form, settings: { ...s, prizes: s.prizes.filter((_, j) => j !== i) } })}><Trash2 className="h-4 w-4" /></Button>
          </div>
        ))}
        <Button type="button" size="sm" variant="outline" onClick={() => setForm({ ...form, settings: { ...s, prizes: [...s.prizes, { from_rank: s.prizes.length + 1, to_rank: s.prizes.length + 1, title: '', prize: '' }] } })}>
          <Plus className="h-3.5 w-3.5 mr-1" /> Add tier
        </Button>
      </Section>
      <Section title="Certificates & Q&A">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <ToggleField label="Issue certificates" checked={s.certificate.enabled} onChange={(v) => setGroup('certificate', 'enabled', v)} />
          <NumField label="Winner certificate for top N teams" value={s.certificate.winner_top_n} onChange={(v) => setGroup('certificate', 'winner_top_n', v)} hint="0 = none" />
          <NumField label="Participation needs ≥ N solved" value={s.certificate.participation_min_solved} onChange={(v) => setGroup('certificate', 'participation_min_solved', v)} hint="0 = any submission" />
          <SelectField label="Issue" value={s.certificate.issue_after} onChange={(v) => setGroup('certificate', 'issue_after', v)}
            options={[['anytime', 'Any time'], ['ended', 'After the contest ends']]} />
          <ToggleField label="Allow participant questions" checked={s.clarifications_enabled} onChange={(v) => setForm({ ...form, settings: { ...s, clarifications_enabled: v } })} />
        </div>
      </Section>
    </div>
  );
}
