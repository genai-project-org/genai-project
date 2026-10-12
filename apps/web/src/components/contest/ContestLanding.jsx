import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Loader2, Sparkles, Users, Clock, CheckCircle2, Plus, UserPlus, Search, User as UserIcon } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

// Fixed accent palette — the LLM only ever picks a KEY from this set (see
// LANDING_ACCENTS in services/contest_service.py), it never supplies raw
// colors or markup. Rendering stays entirely in our own template code.
const ACCENTS = {
  indigo: { text: 'text-indigo-600 dark:text-indigo-400', bg: 'bg-indigo-500', soft: 'bg-indigo-500/10', border: 'border-indigo-500/30', grad: 'from-indigo-500/20 via-indigo-500/5 to-transparent' },
  violet: { text: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-500', soft: 'bg-violet-500/10', border: 'border-violet-500/30', grad: 'from-violet-500/20 via-violet-500/5 to-transparent' },
  emerald: { text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500', soft: 'bg-emerald-500/10', border: 'border-emerald-500/30', grad: 'from-emerald-500/20 via-emerald-500/5 to-transparent' },
  amber: { text: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-500', soft: 'bg-amber-500/10', border: 'border-amber-500/30', grad: 'from-amber-500/20 via-amber-500/5 to-transparent' },
  rose: { text: 'text-rose-600 dark:text-rose-400', bg: 'bg-rose-500', soft: 'bg-rose-500/10', border: 'border-rose-500/30', grad: 'from-rose-500/20 via-rose-500/5 to-transparent' },
  sky: { text: 'text-sky-600 dark:text-sky-400', bg: 'bg-sky-500', soft: 'bg-sky-500/10', border: 'border-sky-500/30', grad: 'from-sky-500/20 via-sky-500/5 to-transparent' },
};

function accentOf(key) {
  return ACCENTS[key] || ACCENTS.indigo;
}

const REG_MODES = [
  { key: 'create', label: 'Create a team', Icon: UserPlus },
  { key: 'join', label: 'Join an open team', Icon: Search },
  { key: 'solo', label: 'Register solo', Icon: UserIcon },
];

function CreateTeamForm({ contestId, onRegistered, accessCode, reg }) {
  const [teamName, setTeamName] = useState('');
  const [teammateEmails, setTeammateEmails] = useState('');
  const [openToJoin, setOpenToJoin] = useState(false);
  const [creating, setCreating] = useState(false);

  const create = async () => {
    if (!teamName.trim() || creating) return;
    setCreating(true);
    try {
      const member_emails = teammateEmails.split(',').map((e) => e.trim()).filter(Boolean);
      await api.post(`/contest/${contestId}/teams`, { name: teamName.trim(), member_emails, open_to_join: openToJoin, access_code: accessCode || undefined });
      toast.success('Team registered!');
      onRegistered?.();
    } catch (e) {
      toast.error(detailToString(e, 'Failed to register team'));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-2.5" data-testid="contest-landing-register-form">
      <Input placeholder="Team name" value={teamName} onChange={(e) => setTeamName(e.target.value)} data-testid="contest-landing-team-name" />
      <Input
        placeholder="Teammate email(s), comma-separated — optional"
        value={teammateEmails}
        onChange={(e) => setTeammateEmails(e.target.value)}
        data-testid="contest-landing-team-emails"
      />
      <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
        <Checkbox checked={openToJoin} onCheckedChange={(v) => setOpenToJoin(Boolean(v))} data-testid="contest-landing-open-to-join" />
        Leave this team open so other solo registrants can join it later
      </label>
      <p className="text-xs text-muted-foreground">A team has {reg?.min_team_size ?? 1}-{reg?.max_team_size ?? 3} members — you're added automatically{(reg?.min_team_size ?? 1) > 1 ? '; invite teammates by email or leave your team open for others to join' : ', teammates are optional'}.</p>
      <Button onClick={create} disabled={creating || !teamName.trim()} data-testid="contest-landing-register-btn">
        {creating ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Plus className="h-4 w-4 mr-2" />}
        Create team
      </Button>
    </div>
  );
}

function JoinOpenTeamForm({ contestId, onRegistered, accessCode }) {
  const [teams, setTeams] = useState(null);
  const [loading, setLoading] = useState(true);
  const [joiningId, setJoiningId] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const { data } = await api.get(`/contest/${contestId}/teams/open`);
        setTeams(data.items || []);
      } catch (e) {
        toast.error(detailToString(e, 'Failed to load open teams'));
        setTeams([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [contestId]);

  const join = async (teamId) => {
    if (joiningId) return;
    setJoiningId(teamId);
    try {
      await api.post(`/contest/${contestId}/teams/${teamId}/join`, { access_code: accessCode || undefined });
      toast.success('Joined the team!');
      onRegistered?.();
    } catch (e) {
      toast.error(detailToString(e, 'Failed to join team'));
    } finally {
      setJoiningId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-3 justify-center">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Looking for open teams…
      </div>
    );
  }

  if (!teams?.length) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="contest-landing-no-open-teams">
        No open teams yet — be the first: create a team and leave it open for others, or register solo.
      </p>
    );
  }

  return (
    <div className="space-y-2" data-testid="contest-landing-open-teams">
      {teams.map((t) => (
        <div key={t.id} className="flex items-center gap-2 rounded-md border border-border px-3 py-2" data-testid={`contest-landing-open-team-${t.id}`}>
          <span className="flex-1 text-sm font-medium truncate">{t.name}</span>
          <Badge variant="secondary" className="shrink-0 text-[11px]">{t.member_count}/{t.max_size || 3} members</Badge>
          <Button
            size="sm" variant="outline"
            onClick={() => join(t.id)} disabled={joiningId !== null}
            data-testid={`contest-landing-join-btn-${t.id}`}
          >
            {joiningId === t.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : `Join (${t.spots_left} left)`}
          </Button>
        </div>
      ))}
    </div>
  );
}

function SoloRegisterForm({ contestId, defaultName, onRegistered, accessCode }) {
  const [registering, setRegistering] = useState(false);

  const registerSolo = async () => {
    if (registering) return;
    setRegistering(true);
    try {
      await api.post(`/contest/${contestId}/teams`, {
        name: defaultName ? `${defaultName}'s Team` : 'Solo Team',
        member_emails: [],
        open_to_join: false,
        access_code: accessCode || undefined,
      });
      toast.success("You're registered!");
      onRegistered?.();
    } catch (e) {
      toast.error(detailToString(e, 'Failed to register'));
    } finally {
      setRegistering(false);
    }
  };

  return (
    <div className="space-y-2.5" data-testid="contest-landing-solo-form">
      <p className="text-xs text-muted-foreground">
        Don't have teammates yet? Register solo now as a team of one — you can grow your team later, or an
        admin/leaderboard will still track your own solves.
      </p>
      <Button onClick={registerSolo} disabled={registering} data-testid="contest-landing-solo-register-btn">
        {registering ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <UserIcon className="h-4 w-4 mr-2" />}
        Register solo
      </Button>
    </div>
  );
}

/**
 * The three explicit, non-ambiguous registration paths: create a team
 * (teammates optional), browse + join an already-open team with no email
 * needed, or register solo outright. A single form that assumed you already
 * had 1-2 named teammates in hand was the actual UX problem this replaces.
 */
function RegistrationOptions({ contest, userName, onRegistered }) {
  const contestId = contest.id;
  const reg = contest.registration || {};
  const available = REG_MODES.filter(({ key }) => (reg.mode === 'solo' ? key === 'solo' : reg.mode === 'team' ? key !== 'solo' : true));
  const [mode, setMode] = useState(available[0]?.key || 'create');
  const [accessCode, setAccessCode] = useState('');

  if (contest.status === 'ended') {
    return (
      <p className="text-sm text-muted-foreground" data-testid="contest-landing-closed">
        Registration is closed — this contest has already ended.
      </p>
    );
  }
  if (reg.open === false) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="contest-landing-closed">
        {reg.reason || 'Registration is closed.'}
      </p>
    );
  }
  if (reg.access === 'invite_only' && contest.invited === false) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="contest-landing-invite-only">
        This contest is invite-only. Sign in with the email address you were invited on to register.
      </p>
    );
  }

  return (
    <div data-testid="contest-landing-registration-options">
      {reg.access === 'code' && (
        <Input
          className="mb-3" placeholder="Access code" value={accessCode}
          onChange={(e) => setAccessCode(e.target.value)} data-testid="contest-landing-access-code"
        />
      )}
      {reg.spots_left != null && (
        <p className="text-[11px] text-muted-foreground mb-2">{reg.spots_left} spot(s) left</p>
      )}
      <div className={cn('grid gap-1.5 mb-3 rounded-lg bg-muted p-1', available.length === 1 ? 'grid-cols-1' : available.length === 2 ? 'grid-cols-2' : 'grid-cols-3')}>
        {available.map(({ key, label, Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setMode(key)}
            data-testid={`contest-landing-mode-${key}`}
            className={cn(
              'flex flex-col items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition-colors',
              mode === key ? 'bg-background shadow text-foreground' : 'text-muted-foreground hover:text-foreground'
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>
      {mode === 'create' && <CreateTeamForm contestId={contestId} onRegistered={onRegistered} accessCode={accessCode} reg={reg} />}
      {mode === 'join' && <JoinOpenTeamForm contestId={contestId} onRegistered={onRegistered} accessCode={accessCode} />}
      {mode === 'solo' && <SoloRegisterForm contestId={contestId} defaultName={userName} onRegistered={onRegistered} accessCode={accessCode} />}
    </div>
  );
}

function Highlights({ highlights, accent }) {
  return (
    <ul className="space-y-2">
      {highlights.map((h, i) => (
        <li key={i} className="flex items-start gap-2 text-sm" data-testid={`contest-landing-highlight-${i}`}>
          <CheckCircle2 className={cn('h-4 w-4 mt-0.5 shrink-0', accent.text)} />
          <span>{h}</span>
        </li>
      ))}
    </ul>
  );
}

function CenteredLayout({ copy, accent, contest, userName, onRegistered }) {
  return (
    <div className={cn('rounded-xl border p-8 bg-gradient-to-b text-center', accent.border, accent.grad)}>
      <Badge variant="outline" className={cn('mb-4', accent.text, accent.border)}>
        <Sparkles className="h-3 w-3 mr-1" /> Hackathon Contest
      </Badge>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight mb-3">{copy.headline}</h1>
      <p className="text-muted-foreground max-w-xl mx-auto mb-6">{copy.tagline}</p>
      <div className="max-w-sm mx-auto text-left mb-6">
        <Highlights highlights={copy.highlights} accent={accent} />
      </div>
      <div className="max-w-sm mx-auto rounded-lg border border-border bg-card p-4 text-left">
        <RegistrationOptions contest={contest} userName={userName} onRegistered={onRegistered} />
      </div>
    </div>
  );
}

function SplitLayout({ copy, accent, contest, userName, onRegistered }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 rounded-xl border border-border overflow-hidden">
      <div className={cn('p-8 bg-gradient-to-br', accent.grad)}>
        <Badge variant="outline" className={cn('mb-4', accent.text, accent.border)}>
          <Sparkles className="h-3 w-3 mr-1" /> Hackathon Contest
        </Badge>
        <h1 className="font-display text-3xl font-semibold tracking-tight mb-3">{copy.headline}</h1>
        <p className="text-muted-foreground mb-6">{copy.tagline}</p>
        <Highlights highlights={copy.highlights} accent={accent} />
      </div>
      <div className="p-8 flex items-center">
        <div className="w-full rounded-lg border border-border bg-card p-5">
          <div className="flex items-center gap-1.5 font-medium mb-3">
            <Users className={cn('h-4 w-4', accent.text)} /> Register your team
          </div>
          <RegistrationOptions contest={contest} userName={userName} onRegistered={onRegistered} />
        </div>
      </div>
    </div>
  );
}

function CardsLayout({ copy, accent, contest, userName, onRegistered }) {
  return (
    <div className="rounded-xl border border-border p-8 space-y-6">
      <div className="text-center">
        <Badge variant="outline" className={cn('mb-4', accent.text, accent.border)}>
          <Sparkles className="h-3 w-3 mr-1" /> Hackathon Contest
        </Badge>
        <h1 className="font-display text-3xl font-semibold tracking-tight mb-3">{copy.headline}</h1>
        <p className="text-muted-foreground max-w-xl mx-auto">{copy.tagline}</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {copy.highlights.map((h, i) => (
          <div key={i} className={cn('rounded-lg border p-4 text-sm', accent.border, accent.soft)} data-testid={`contest-landing-highlight-${i}`}>
            <CheckCircle2 className={cn('h-4 w-4 mb-2', accent.text)} />
            {h}
          </div>
        ))}
      </div>
      <div className="max-w-md mx-auto rounded-lg border border-border bg-card p-5">
        <div className="flex items-center gap-1.5 font-medium mb-3 justify-center">
          <Users className={cn('h-4 w-4', accent.text)} /> Register your team
        </div>
        <RegistrationOptions contest={contest} userName={userName} onRegistered={onRegistered} />
      </div>
    </div>
  );
}

const LAYOUTS = { centered: CenteredLayout, split: SplitLayout, cards: CardsLayout };

/**
 * The default view for a contest to a user who has NOT yet registered a
 * team. Renders the structured, LLM-generated (or deterministic-fallback)
 * copy from contest.landing_page through one of a small fixed set of
 * hand-built React templates — real per-contest variation (copy, color,
 * layout) with zero raw/untrusted markup ever executed.
 */
export default function ContestLanding({ contest, userName, onRegistered }) {
  const branding = contest.settings?.branding || {};
  const base = contest.landing_page || {
    headline: `Register for ${contest.name}`,
    tagline: 'A free, team-based coding contest.',
    highlights: ['Free entry', 'Team-based', 'Live leaderboard'],
    accent: 'indigo',
    layout: 'centered',
  };
  // Admin-authored headline/tagline (Settings > Branding) win over the generated copy.
  const copy = { ...base, headline: branding.headline || base.headline, tagline: branding.tagline || base.tagline };
  const prizes = contest.settings?.prizes || [];
  const accent = accentOf(copy.accent);
  const Layout = LAYOUTS[copy.layout] || CenteredLayout;

  return (
    <div data-testid="contest-landing-page">
      {branding.banner_url && (
        <img
          src={branding.banner_url} alt=""
          className="w-full max-h-56 object-cover rounded-xl border border-border mb-4"
          data-testid="contest-landing-banner"
        />
      )}
      <Layout copy={copy} accent={accent} contest={contest} userName={userName} onRegistered={onRegistered} />

      <div className="mt-6 rounded-lg border border-border bg-card p-5" data-testid="contest-landing-problems">
        <div className="flex items-center justify-between mb-3">
          <div className="font-medium text-sm">Problem set ({contest.problems.length})</div>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            {new Date(contest.start_at).toLocaleString()} &rarr; {new Date(contest.end_at).toLocaleString()}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {contest.problems.map((p) => (
            <Badge key={p.id} variant="secondary">{p.locked ? 'Locked problem' : p.title}{p.points ? ` · ${p.points} pts` : ''}</Badge>
          ))}
        </div>
      </div>

      {(branding.description || branding.rules_text || prizes.length > 0) && (
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          {(branding.description || branding.rules_text) && (
            <div className="rounded-lg border border-border bg-card p-5" data-testid="contest-landing-rules">
              {branding.description && <p className="text-sm mb-3">{branding.description}</p>}
              {branding.rules_text && (
                <>
                  <div className="font-medium text-sm mb-1.5">Rules</div>
                  <p className="text-xs text-muted-foreground whitespace-pre-line">{branding.rules_text}</p>
                </>
              )}
            </div>
          )}
          {prizes.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-5" data-testid="contest-landing-prizes">
              <div className="font-medium text-sm mb-2">Prizes</div>
              <ul className="space-y-1.5 text-sm">
                {prizes.map((t, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <Badge variant="outline" className="shrink-0">{t.from_rank === t.to_rank ? `#${t.from_rank}` : `#${t.from_rank}-${t.to_rank}`}</Badge>
                    <span><span className="font-medium">{t.title}</span>{t.prize ? ` — ${t.prize}` : ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
