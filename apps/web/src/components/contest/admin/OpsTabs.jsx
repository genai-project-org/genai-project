import { useCallback, useEffect, useState } from 'react';
import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Archive, Copy, Download, Loader2, Octagon, Pause, Play, PlayCircle, Timer, Trash2, UserPlus, Megaphone, Eye,
} from 'lucide-react';
import { toast } from 'sonner';
import { Field, Section, detailToString, downloadBlob } from './shared';

const STATUS_BADGE = {
  draft: 'bg-muted text-muted-foreground border-border',
  upcoming: 'bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30',
  live: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  paused: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  ended: 'bg-muted text-muted-foreground border-border',
};

function Confirm({ trigger, title, description, action, onConfirm, testid }) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm} className="bg-destructive text-destructive-foreground hover:bg-destructive/90" data-testid={testid}>
            {action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ---------------------------------------------------------------------------
// Lifecycle bar (Overview tab, edit mode)
// ---------------------------------------------------------------------------
export function LifecycleBar({ admin, onChanged, onDeleted }) {
  const [busy, setBusy] = useState(null);
  const [minutes, setMinutes] = useState(30);
  const id = admin.id;
  const run = async (key, fn, okMsg) => {
    setBusy(key);
    try {
      await fn();
      toast.success(okMsg);
      await onChanged?.();
    } catch (e) {
      toast.error(detailToString(e, 'Action failed'));
    } finally {
      setBusy(null);
    }
  };
  const post = (path, body) => () => api.post(`/contest/${id}/${path}`, body ?? {});
  const status = admin.status;
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="contest-lifecycle">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Lifecycle</span>
        <Badge variant="outline" className={STATUS_BADGE[status] || ''} data-testid="contest-admin-status">{status}</Badge>
        {admin.archived && <Badge variant="secondary">archived</Badge>}
        <span className="text-xs text-muted-foreground ml-auto">
          {admin.team_count} team(s) · {admin.participant_count} participant(s) · {admin.submission_count} submission(s)
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {(status === 'draft' || status === 'upcoming') && (
          <Button size="sm" onClick={() => run('start', post('start-now'), 'Contest started')} disabled={!!busy} data-testid="contest-start-now">
            <PlayCircle className="h-4 w-4 mr-1.5" /> Start now
          </Button>
        )}
        {status === 'live' && (
          <Button size="sm" variant="outline" onClick={() => run('pause', post('pause'), 'Contest paused')} disabled={!!busy} data-testid="contest-pause">
            <Pause className="h-4 w-4 mr-1.5" /> Pause
          </Button>
        )}
        {status === 'paused' && (
          <Button size="sm" onClick={() => run('resume', post('resume'), 'Contest resumed')} disabled={!!busy} data-testid="contest-resume">
            <Play className="h-4 w-4 mr-1.5" /> Resume
          </Button>
        )}
        {status !== 'draft' && (
          <div className="flex items-center gap-1.5">
            <Input type="number" min={1} className="w-20 h-8" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} data-testid="contest-extend-minutes" />
            <Button size="sm" variant="outline" onClick={() => run('extend', post('extend', { minutes }), `Extended by ${minutes} min`)} disabled={!!busy || !(minutes >= 1)} data-testid="contest-extend">
              <Timer className="h-4 w-4 mr-1.5" /> {status === 'ended' ? 'Reopen for' : 'Extend by'} (min)
            </Button>
          </div>
        )}
        {status !== 'ended' && status !== 'draft' && (
          <Confirm
            testid="contest-stop-confirm"
            trigger={<Button size="sm" variant="destructive" data-testid="contest-stop-btn"><Octagon className="h-4 w-4 mr-1.5" /> End now</Button>}
            title={`End "${admin.name}" now?`}
            description="This immediately ends the contest for every participant, regardless of its scheduled end time. You can reopen it later with Extend."
            action="End contest now"
            onConfirm={() => run('stop', post('stop'), 'Contest ended')}
          />
        )}
        <Button size="sm" variant="outline" onClick={() => run('archive', post('archive', { archived: !admin.archived }), admin.archived ? 'Unarchived' : 'Archived')} disabled={!!busy} data-testid="contest-archive">
          <Archive className="h-4 w-4 mr-1.5" /> {admin.archived ? 'Unarchive' : 'Archive'}
        </Button>
        <Button size="sm" variant="outline" onClick={() => run('dup', post('duplicate'), 'Duplicated as a draft')} disabled={!!busy} data-testid="contest-duplicate">
          <Copy className="h-4 w-4 mr-1.5" /> Duplicate
        </Button>
        <Confirm
          testid="contest-delete-confirm"
          trigger={<Button size="sm" variant="outline" className="text-destructive" data-testid="contest-delete"><Trash2 className="h-4 w-4 mr-1.5" /> Delete</Button>}
          title={`Delete "${admin.name}"?`}
          description="This permanently deletes the contest with all its teams, submissions, announcements and questions. This cannot be undone."
          action="Delete permanently"
          onConfirm={async () => {
            try {
              await api.delete(`/contest/${id}`);
              toast.success('Contest deleted');
              onDeleted?.();
            } catch (e) {
              toast.error(detailToString(e, 'Delete failed'));
            }
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scoring operations: manual adjustments, rejudge, plagiarism, audit
// ---------------------------------------------------------------------------
export function ScoringOps({ contestId, problems }) {
  const [teams, setTeams] = useState([]);
  const [adjs, setAdjs] = useState([]);
  const [audit, setAudit] = useState([]);
  const [flags, setFlags] = useState(null);
  const [f, setF] = useState({ team_id: '', kind: 'grace', points: 0, penalty_minutes: 0, reason: '' });
  const [rejudging, setRejudging] = useState(null);

  const load = useCallback(async () => {
    try {
      const [lb, a, au] = await Promise.all([
        api.get(`/contest/${contestId}/leaderboard`), api.get(`/contest/${contestId}/adjustments`), api.get(`/contest/${contestId}/audit`),
      ]);
      setTeams(lb.data.items || []);
      setAdjs(a.data.items || []);
      setAudit(au.data.items || []);
    } catch (e) {
      toast.error(detailToString(e, 'Failed to load scoring data'));
    }
  }, [contestId]);
  useEffect(() => { load(); }, [load]);

  const add = async () => {
    try {
      await api.post(`/contest/${contestId}/adjustments`, { ...f, points: Number(f.points), penalty_minutes: Number(f.penalty_minutes) });
      toast.success('Adjustment recorded');
      setF({ ...f, points: 0, penalty_minutes: 0, reason: '' });
      load();
    } catch (e) {
      toast.error(detailToString(e, 'Failed to add adjustment'));
    }
  };
  const rejudge = async (pid) => {
    setRejudging(pid);
    try {
      const { data } = await api.post(`/contest/${contestId}/rejudge`, { problem_id: pid });
      toast.success(`Rejudged ${data.rejudged} submission(s), ${data.changed} changed`);
      load();
    } catch (e) {
      toast.error(detailToString(e, 'Rejudge failed'));
    } finally {
      setRejudging(null);
    }
  };
  const teamName = (id) => teams.find((t) => t.team_id === id)?.team_name || id.slice(0, 6);

  return (
    <div className="space-y-4" data-testid="contest-tab-scoring-ops">
      <Section title="Manual adjustment (grace marks / score override)" hint="Every adjustment needs a reason and is written to the audit log.">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2 items-end">
          <Field label="Team" className="col-span-2">
            <Select value={f.team_id} onValueChange={(v) => setF({ ...f, team_id: v })}>
              <SelectTrigger data-testid="adj-team"><SelectValue placeholder="Choose team" /></SelectTrigger>
              <SelectContent>{teams.map((t) => <SelectItem key={t.team_id} value={t.team_id}>{t.team_name}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Type">
            <Select value={f.kind} onValueChange={(v) => setF({ ...f, kind: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="grace">Grace (add/subtract)</SelectItem><SelectItem value="override">Override total score</SelectItem></SelectContent>
            </Select>
          </Field>
          <Field label="Points"><Input type="number" value={f.points} onChange={(e) => setF({ ...f, points: e.target.value })} data-testid="adj-points" /></Field>
          <Field label="Penalty min (-)"><Input type="number" value={f.penalty_minutes} onChange={(e) => setF({ ...f, penalty_minutes: e.target.value })} disabled={f.kind === 'override'} /></Field>
          <Field label="Reason" className="col-span-2 md:col-span-6"><Input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="e.g. judge outage, manual review" data-testid="adj-reason" /></Field>
        </div>
        <Button size="sm" onClick={add} disabled={!f.team_id || f.reason.trim().length < 3} data-testid="adj-add">Record adjustment</Button>
        {adjs.length > 0 && (
          <div className="divide-y divide-border text-xs rounded-md border border-border">
            {adjs.map((a) => (
              <div key={a.id} className="flex items-center gap-2 px-3 py-1.5">
                <Badge variant="outline">{a.kind}</Badge>
                <span className="font-medium">{teamName(a.team_id)}</span>
                <span>{a.kind === 'override' ? `= ${a.points}` : `${a.points >= 0 ? '+' : ''}${a.points} pts, ${a.penalty_minutes} min`}</span>
                <span className="text-muted-foreground flex-1 truncate">{a.reason}</span>
                <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive" onClick={async () => { await api.delete(`/contest/${contestId}/adjustments/${a.id}`); load(); }}><Trash2 className="h-3.5 w-3.5" /></Button>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section title="Rejudge & integrity" hint="Rejudge re-runs stored code with the problem's current limits. Duplicate check flags identical passing solutions from different teams.">
        <div className="flex flex-wrap gap-2">
          {problems.map((p) => (
            <Button key={p.id} size="sm" variant="outline" onClick={() => rejudge(p.id)} disabled={rejudging !== null} data-testid={`rejudge-${p.id}`}>
              {rejudging === p.id && <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />} Rejudge {p.title}
            </Button>
          ))}
        </div>
        <Button size="sm" variant="outline" onClick={async () => { const { data } = await api.get(`/contest/${contestId}/plagiarism`); setFlags(data.items); }}>
          Check duplicate solutions
        </Button>
        {flags && (flags.length === 0
          ? <p className="text-xs text-muted-foreground">No duplicate passing solutions found.</p>
          : flags.map((g, i) => <p key={i} className="text-xs">Identical solution to <b>{g.problem_id}</b> from: {g.team_names.join(', ')}</p>))}
      </Section>
      <Section title="Audit log">
        <div className="max-h-56 overflow-y-auto divide-y divide-border text-xs rounded-md border border-border" data-testid="contest-audit-log">
          {audit.length === 0 && <p className="p-3 text-muted-foreground">No admin actions yet.</p>}
          {audit.map((a) => (
            <div key={a.id} className="px-3 py-1.5 flex gap-2">
              <span className="text-muted-foreground w-36 shrink-0">{new Date(a.created_at).toLocaleString()}</span>
              <span className="font-medium w-36 shrink-0">{a.action}</span>
              <span className="text-muted-foreground truncate">{Object.entries(a.details || {}).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ')}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Participants
// ---------------------------------------------------------------------------
export function ParticipantsTab({ contestId, onChanged }) {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState('');
  const [email, setEmail] = useState('');
  const [invites, setInvites] = useState('');
  const [reason, setReason] = useState('');

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/contest/${contestId}/participants`, { params: { q } });
      setRows(data.items);
    } catch (e) {
      toast.error(detailToString(e, 'Failed to load participants'));
    }
  }, [contestId, q]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);

  const act = async (fn, msg) => {
    try { await fn(); toast.success(msg); await load(); onChanged?.(); } catch (e) { toast.error(detailToString(e, 'Action failed')); }
  };
  const base = `/contest/${contestId}`;
  return (
    <div className="space-y-4" data-testid="contest-panel-participants">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Section title="Add a participant" hint="Bypasses cap, window and access rules. The person must already have an account.">
          <div className="flex gap-2">
            <Input placeholder="user@email.com" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="participant-add-email" />
            <Button size="sm" disabled={!email.trim()} onClick={() => act(async () => { await api.post(`${base}/participants`, { email }); setEmail(''); }, 'Participant added')} data-testid="participant-add">
              <UserPlus className="h-4 w-4 mr-1.5" /> Add
            </Button>
          </div>
        </Section>
        <Section title="Bulk invite by email" hint="One per line or comma-separated. Sends an invitation and allows registration on invite-only contests.">
          <Textarea rows={3} value={invites} onChange={(e) => setInvites(e.target.value)} placeholder="a@x.com, b@y.com" data-testid="invite-emails" />
          <Button size="sm" disabled={!invites.trim()} data-testid="invite-send"
            onClick={() => act(async () => {
              const emails = invites.split(/[\s,;]+/).filter(Boolean);
              const { data } = await api.post(`${base}/invites`, { emails });
              toast.message(`${data.added.length} invited, ${data.already_invited.length} already invited, ${data.invalid.length} invalid`);
              setInvites('');
            }, 'Invites processed')}>Send invites</Button>
        </Section>
      </div>
      <div className="flex items-center gap-2">
        <Input placeholder="Search name, email or team" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" data-testid="participant-search" />
        <Input placeholder="Reason for disqualification" value={reason} onChange={(e) => setReason(e.target.value)} className="max-w-xs" data-testid="dq-reason" />
      </div>
      <div className="rounded-md border border-border divide-y divide-border text-sm" data-testid="participants-table">
        {rows === null && <div className="p-4 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin inline mr-1" />Loading…</div>}
        {rows?.length === 0 && <p className="p-4 text-xs text-muted-foreground">No participants yet.</p>}
        {rows?.map((r) => (
          <div key={r.user_id} className="flex flex-wrap items-center gap-2 px-3 py-2" data-testid={`participant-row-${r.user_id}`}>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{r.name} <span className="text-xs text-muted-foreground font-normal">{r.email}</span></div>
              <div className="text-xs text-muted-foreground">{r.team_name} · {r.team_size} member(s) · {r.submissions} submission(s)</div>
            </div>
            {(r.team_disqualified || r.user_disqualified) && <Badge variant="destructive">disqualified</Badge>}
            {r.team_disqualified
              ? <Button size="sm" variant="outline" onClick={() => act(() => api.post(`${base}/teams/${r.team_id}/reinstate`), 'Team reinstated')}>Reinstate team</Button>
              : <Button size="sm" variant="outline" disabled={reason.trim().length < 3} title="Enter a reason above" onClick={() => act(() => api.post(`${base}/teams/${r.team_id}/disqualify`, { reason }), 'Team disqualified')} data-testid={`dq-team-${r.team_id}`}>Disqualify team</Button>}
            {r.user_disqualified
              ? <Button size="sm" variant="outline" onClick={() => act(() => api.post(`${base}/participants/${r.user_id}/reinstate`), 'Participant reinstated')}>Reinstate person</Button>
              : <Button size="sm" variant="outline" disabled={reason.trim().length < 3} onClick={() => act(() => api.post(`${base}/participants/${r.user_id}/disqualify`, { reason }), 'Participant disqualified')}>Disqualify person</Button>}
            <Confirm
              trigger={<Button size="sm" variant="ghost" className="text-destructive"><Trash2 className="h-3.5 w-3.5" /></Button>}
              title={`Remove ${r.name}?`} description="They are removed from their team (an empty team is deleted)." action="Remove"
              onConfirm={() => act(() => api.delete(`${base}/participants/${r.user_id}`), 'Participant removed')}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Announcements + clarification inbox
// ---------------------------------------------------------------------------
export function AnnouncementsTab({ contestId }) {
  const [items, setItems] = useState([]);
  const [clar, setClar] = useState([]);
  const [text, setText] = useState('');
  const [pinned, setPinned] = useState(false);
  const [answers, setAnswers] = useState({});
  const base = `/contest/${contestId}`;
  const load = useCallback(async () => {
    try {
      const [a, c] = await Promise.all([api.get(`${base}/announcements`), api.get(`${base}/clarifications`)]);
      setItems(a.data.items);
      setClar(c.data.items);
    } catch (e) {
      toast.error(detailToString(e, 'Failed to load'));
    }
  }, [base]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4" data-testid="contest-panel-announcements">
      <Section title="Broadcast to participants" hint="Shown live at the top of the contest page (refreshes every 15 seconds).">
        <Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Problem 3 statement clarified…" data-testid="announce-text" />
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-1.5 text-xs"><Checkbox checked={pinned} onCheckedChange={setPinned} /> Pin to top</label>
          <Button size="sm" disabled={!text.trim()} data-testid="announce-send"
            onClick={async () => {
              try { await api.post(`${base}/announcements`, { text, pinned }); setText(''); setPinned(false); toast.success('Announcement sent'); load(); }
              catch (e) { toast.error(detailToString(e, 'Failed to send')); }
            }}>
            <Megaphone className="h-4 w-4 mr-1.5" /> Send
          </Button>
        </div>
        <div className="divide-y divide-border rounded-md border border-border text-sm">
          {items.length === 0 && <p className="p-3 text-xs text-muted-foreground">No announcements yet.</p>}
          {items.map((a) => (
            <div key={a.id} className="flex items-start gap-2 px-3 py-2">
              {a.pinned && <Badge variant="secondary">pinned</Badge>}
              <span className="flex-1">{a.text}</span>
              <span className="text-[11px] text-muted-foreground">{new Date(a.created_at).toLocaleString()}</span>
              <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive" onClick={async () => { await api.delete(`${base}/announcements/${a.id}`); load(); }}><Trash2 className="h-3.5 w-3.5" /></Button>
            </div>
          ))}
        </div>
      </Section>
      <Section title={`Questions from participants (${clar.filter((c) => !c.answer).length} unanswered)`}>
        {clar.length === 0 && <p className="text-xs text-muted-foreground">No questions yet.</p>}
        {clar.map((c) => {
          const a = answers[c.id] || { text: '', public: true };
          return (
            <div key={c.id} className="rounded-md border border-border p-3 space-y-2" data-testid={`clar-${c.id}`}>
              <div className="text-sm"><span className="text-xs text-muted-foreground">{c.user_name}{c.problem_id ? ` · ${c.problem_id}` : ''}:</span> {c.question}</div>
              {c.answer && <div className="text-sm rounded bg-muted px-2 py-1">A: {c.answer} {c.public && <Badge variant="outline" className="ml-1">public</Badge>}</div>}
              <div className="flex items-center gap-2">
                <Input placeholder={c.answer ? 'Update answer' : 'Write an answer'} value={a.text} onChange={(e) => setAnswers({ ...answers, [c.id]: { ...a, text: e.target.value } })} />
                <label className="flex items-center gap-1 text-xs shrink-0"><Checkbox checked={a.public} onCheckedChange={(v) => setAnswers({ ...answers, [c.id]: { ...a, public: !!v } })} /> share with all</label>
                <Button size="sm" disabled={!a.text.trim()} onClick={async () => { await api.post(`${base}/clarifications/${c.id}/answer`, { answer: a.text, public: a.public }); setAnswers({ ...answers, [c.id]: undefined }); load(); }}>Answer</Button>
              </div>
            </div>
          );
        })}
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Leaderboard operations: live admin standings, reveal, CSV export
// ---------------------------------------------------------------------------
export function LeaderboardOps({ contestId, onChanged }) {
  const [data, setData] = useState(null);
  const load = useCallback(async () => {
    try { setData((await api.get(`/contest/${contestId}/leaderboard`)).data); } catch (e) { toast.error(detailToString(e, 'Failed to load standings')); }
  }, [contestId]);
  useEffect(() => { load(); }, [load]);
  const dl = async (kind) => {
    try { await downloadBlob(`/contest/${contestId}/export/${kind}.csv`, `${kind}-${contestId}.csv`); }
    catch (e) { toast.error(detailToString(e, 'Export failed')); }
  };
  const reveal = async (revealed) => {
    try { await api.post(`/contest/${contestId}/leaderboard/reveal`, { revealed }); toast.success(revealed ? 'Leaderboard revealed to everyone' : 'Freeze/visibility rules re-applied'); load(); onChanged?.(); }
    catch (e) { toast.error(detailToString(e, 'Failed')); }
  };
  const view = data?.admin_view;
  return (
    <Section title="Live standings (admin view)" hint="You always see live standings, including disqualified teams. Participants see what the visibility/freeze rules allow.">
      <div className="flex flex-wrap items-center gap-2">
        {view?.participant_hidden && <Badge variant="secondary">hidden from participants</Badge>}
        {view?.participant_frozen && <Badge variant="secondary">frozen for participants</Badge>}
        <Button size="sm" variant="outline" onClick={() => reveal(true)} data-testid="lb-reveal"><Eye className="h-4 w-4 mr-1.5" /> Reveal to everyone</Button>
        <Button size="sm" variant="outline" onClick={() => reveal(false)}>Re-apply rules</Button>
        <Button size="sm" variant="outline" onClick={load}>Refresh</Button>
        <Button size="sm" variant="outline" onClick={() => dl('standings')} data-testid="export-standings"><Download className="h-4 w-4 mr-1.5" /> Standings CSV</Button>
        <Button size="sm" variant="outline" onClick={() => dl('submissions')} data-testid="export-submissions"><Download className="h-4 w-4 mr-1.5" /> Submissions CSV</Button>
      </div>
      <div className="divide-y divide-border rounded-md border border-border text-sm">
        {!data?.items?.length && <p className="p-3 text-xs text-muted-foreground">No teams yet.</p>}
        {data?.items?.map((r) => (
          <div key={r.team_id} className="flex items-center gap-3 px-3 py-1.5">
            <span className="w-8 text-muted-foreground tabular-nums">{r.rank ? `#${r.rank}` : '—'}</span>
            <span className="flex-1 truncate">{r.team_name} {r.disqualified && <Badge variant="destructive" className="ml-1">DQ</Badge>}</span>
            <span className="text-xs tabular-nums">{r.problems_solved} solved</span>
            <span className="text-xs tabular-nums w-20 text-right">{r.score} pts</span>
            <span className="text-xs tabular-nums w-16 text-right text-muted-foreground">{Math.round(r.penalty_seconds / 60)}m</span>
          </div>
        ))}
      </div>
    </Section>
  );
}
