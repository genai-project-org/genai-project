import { useCallback, useEffect, useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, Plus, Save, X, Zap } from 'lucide-react';
import { toast } from 'sonner';
import {
  DEFAULT_PROBLEM_CONFIG, detailToString, isoToLocalInput, localToIso, withDefaults, Section,
} from './admin/shared';
import { OverviewForm, ProblemsForm, ScoringForm, LeaderboardForm, SettingsForm } from './admin/FormTabs';
import {
  LifecycleBar, ScoringOps, ParticipantsTab, AnnouncementsTab, LeaderboardOps,
} from './admin/OpsTabs';

function defaultForm() {
  const start = new Date();
  start.setMinutes(0, 0, 0);
  start.setHours(start.getHours() + 1);
  const end = new Date(start.getTime() + 2 * 3600 * 1000);
  return {
    name: '', start: isoToLocalInput(start.toISOString()), end: isoToLocalInput(end.toISOString()),
    state: 'published', settings: withDefaults({}), problems: [],
  };
}

const parseList = (txt) => {
  const arr = (txt || '').split(',').map((x) => x.trim()).filter(Boolean).map(Number).filter((n) => Number.isFinite(n));
  return arr.length ? arr : null;
};

// Turn the editable form into the API payload (settings schema lives in
// services/contest_settings.py; the server validates everything again).
function toPayload(form) {
  const s = JSON.parse(JSON.stringify(form.settings));
  s.branding.banner_url = (s.branding.banner_url || '').trim() || null;
  if (s.registration.access !== 'code') s.registration.access_code = null;
  const problem_configs = {};
  for (const p of form.problems) {
    const { ...cfg } = p.config;
    cfg.test_weights = parseList(p._weights);
    cfg.visible_tests = parseList(p._visible)?.map((n) => Math.trunc(n)) || null;
    problem_configs[p.id] = cfg;
  }
  return {
    name: form.name.trim(), start_at: localToIso(form.start), end_at: localToIso(form.end), state: form.state,
    settings: s, problem_ids: form.problems.map((p) => p.id), problem_configs,
  };
}

function QuickCreate({ onCreated }) {
  const [templates, setTemplates] = useState([]);
  const [tpl, setTpl] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get('/contest/templates').then(({ data }) => { setTemplates(data.items || []); setTpl(data.items?.[0]?.id || ''); }).catch(() => {});
  }, []);
  const go = async () => {
    setBusy(true);
    try {
      const { data } = await api.post('/contest/from-template', { template_id: tpl, name: name.trim() });
      toast.success('Contest created and live — customise it any time');
      onCreated?.(data.id);
    } catch (e) {
      toast.error(detailToString(e, 'Failed to create contest'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section title="Quick create from template" hint="Pick a template, name it, go live in one click. Everything stays editable afterwards.">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="contest-templates">
        {templates.map((t) => (
          <button
            key={t.id} type="button" onClick={() => setTpl(t.id)} data-testid={`contest-template-${t.id}`}
            className={`text-left rounded-md border px-3 py-2 transition-colors ${tpl === t.id ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent/50'}`}
          >
            <div className="text-sm font-medium">{t.name}</div>
            <div className="text-[11px] text-muted-foreground">{t.description}</div>
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <Input placeholder="Contest name" value={name} onChange={(e) => setName(e.target.value)} data-testid="contest-quick-name" />
        <Button onClick={go} disabled={busy || !name.trim() || !tpl} data-testid="contest-quick-create">
          {busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Zap className="h-4 w-4 mr-2" />} Create & go live
        </Button>
      </div>
    </Section>
  );
}

/**
 * Admin console for one contest (or the "create" flow). Wired to the real
 * /api/contest endpoints — no client-side-only mock state. Tabs: Overview,
 * Problems, Scoring, Participants, Leaderboard, Announcements, Settings. The
 * form tabs share one `form` object saved with a single PATCH/POST; the
 * Participants / Announcements / Leaderboard-ops / Scoring-ops sections act
 * immediately and need an existing contest.
 *
 * `editingContest`: the selected contest's public payload (only its id is
 * used; the full editable state is fetched from GET /contest/{id}/admin), or
 * null to create a new contest.
 */
export default function ContestAdminPanel({ editingContest, onSaved, onClose, onRefresh, onDeleted }) {
  const [bank, setBank] = useState([]);
  const [admin, setAdmin] = useState(null);
  const [form, setForm] = useState(defaultForm);
  const [loading, setLoading] = useState(Boolean(editingContest));
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState('overview');
  const isEdit = Boolean(editingContest);
  const contestId = editingContest?.id;

  useEffect(() => {
    api.get('/practice/roadmap')
      .then(({ data }) => setBank((data.items || []).filter((i) => i.question_type === 'code')))
      .catch((e) => toast.error(detailToString(e, 'Failed to load the problem bank')));
  }, []);

  const load = useCallback(async () => {
    if (!contestId) { setAdmin(null); setForm(defaultForm()); return; }
    try {
      const { data } = await api.get(`/contest/${contestId}/admin`);
      setAdmin(data);
      setForm({
        name: data.name, start: isoToLocalInput(data.start_at), end: isoToLocalInput(data.end_at), state: data.state || 'published',
        settings: withDefaults(data.settings),
        problems: data.problem_ids.map((id) => {
          const cfg = { ...DEFAULT_PROBLEM_CONFIG, ...(data.problem_configs?.[id] || {}) };
          const b = bank.find((x) => x.id === id);
          return {
            id, title: b?.title || id, difficulty: b?.difficulty || '', config: cfg,
            _weights: (cfg.test_weights || []).join(','), _visible: (cfg.visible_tests || []).join(','),
          };
        }),
      });
    } catch (e) {
      toast.error(detailToString(e, 'Failed to load contest'));
    } finally {
      setLoading(false);
    }
    // bank is only used for display titles; re-load when it arrives
  }, [contestId, bank]);
  useEffect(() => { load(); }, [load]);

  const canSave = form.name.trim() && form.start && form.end && form.problems.length > 0 && !saving;

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const payload = toPayload(form);
      if (isEdit) {
        await api.patch(`/contest/${contestId}`, payload);
        toast.success('Changes saved');
        await load();
        onRefresh?.();
      } else {
        const { data } = await api.post('/contest/', { ...payload, ai_landing: false });
        toast.success('Contest created');
        onSaved?.(data.id);
      }
    } catch (e) {
      toast.error(detailToString(e, isEdit ? 'Failed to save changes' : 'Failed to create contest'));
    } finally {
      setSaving(false);
    }
  };

  const needsContest = (node) => (isEdit ? node : (
    <p className="text-sm text-muted-foreground py-6 text-center">Create the contest first — this section manages a contest that already exists.</p>
  ));
  const isLive = admin && (admin.status === 'live' || admin.status === 'paused');

  return (
    <div className="mb-6 rounded-lg border border-border bg-card p-4 space-y-4" data-testid="contest-admin-form">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">{isEdit ? `Manage "${editingContest.name}"` : 'Create a new contest'}</div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} data-testid="contest-admin-close">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {!isEdit && <QuickCreate onCreated={(id) => onSaved?.(id)} />}

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-6 justify-center">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
        </div>
      ) : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="flex flex-wrap h-auto" data-testid="contest-admin-tabs">
            {[['overview', 'Overview'], ['problems', 'Problems'], ['scoring', 'Scoring'], ['participants', 'Participants'],
              ['leaderboard', 'Leaderboard'], ['announcements', 'Announcements'], ['settings', 'Settings']].map(([v, l]) => (
              <TabsTrigger key={v} value={v} data-testid={`contest-tab-${v}`}>{l}</TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview" className="space-y-4 pt-3">
            <OverviewForm form={form} setForm={setForm} />
            {isEdit && admin && <LifecycleBar admin={admin} onChanged={async () => { await load(); onRefresh?.(); }} onDeleted={onDeleted} />}
          </TabsContent>
          <TabsContent value="problems" className="pt-3"><ProblemsForm form={form} setForm={setForm} bank={bank} isLive={isLive} /></TabsContent>
          <TabsContent value="scoring" className="space-y-4 pt-3">
            <ScoringForm form={form} setForm={setForm} />
            {needsContest(<ScoringOps contestId={contestId} problems={form.problems} />)}
          </TabsContent>
          <TabsContent value="participants" className="pt-3">{needsContest(<ParticipantsTab contestId={contestId} onChanged={onRefresh} />)}</TabsContent>
          <TabsContent value="leaderboard" className="space-y-4 pt-3">
            <LeaderboardForm form={form} setForm={setForm} />
            {needsContest(<LeaderboardOps contestId={contestId} onChanged={onRefresh} />)}
          </TabsContent>
          <TabsContent value="announcements" className="pt-3">{needsContest(<AnnouncementsTab contestId={contestId} />)}</TabsContent>
          <TabsContent value="settings" className="pt-3"><SettingsForm form={form} setForm={setForm} /></TabsContent>
        </Tabs>
      )}

      {!loading && (
        <div className="flex items-center gap-3 pt-1 border-t border-border">
          <Button size="sm" onClick={save} disabled={!canSave} data-testid="contest-admin-save">
            {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : isEdit ? <Save className="h-4 w-4 mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
            {isEdit ? 'Save changes' : 'Create contest'}
          </Button>
          <span className="text-[11px] text-muted-foreground">
            Saves Overview, Problems, Scoring, Leaderboard and Settings together{isLive ? ' — applied live to participants immediately' : ''}.
          </span>
        </div>
      )}
    </div>
  );
}
