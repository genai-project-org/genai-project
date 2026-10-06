import { useEffect, useRef, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import {
  Loader2, Mail, RefreshCw, ChevronDown, Copy, ExternalLink, MapPin, Users, Search, Send,
  FileText, MessageSquareText, IndianRupee,
} from 'lucide-react';
import { toast } from 'sonner';

const STATUS_OPTIONS = [
  { value: 'new', label: 'New' },
  { value: 'applied', label: 'Applied' },
  { value: 'contacted', label: 'Contacted' },
  { value: 'interviewing', label: 'Interviewing' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: 'Rejected' },
];

const ADDON_CONFIG = {
  tailor: { path: 'tailor', label: 'Tailor resume', accent: 'blue', icon: FileText },
  prep: { path: 'interview-prep', label: 'Interview prep', accent: 'violet', icon: MessageSquareText },
  salary: { path: 'salary-coach', label: 'Salary coach', accent: 'emerald', icon: IndianRupee },
};

const ACCENT = {
  blue: { border: 'border-l-2 border-l-blue-500/50', dot: 'bg-blue-500', hover: 'hover:text-blue-600 hover:bg-blue-500/10 dark:hover:text-blue-400' },
  violet: { border: 'border-l-2 border-l-violet-500/50', dot: 'bg-violet-500', hover: 'hover:text-violet-600 hover:bg-violet-500/10 dark:hover:text-violet-400' },
  emerald: { border: 'border-l-2 border-l-emerald-500/50', dot: 'bg-emerald-500', hover: 'hover:text-emerald-600 hover:bg-emerald-500/10 dark:hover:text-emerald-400' },
};

function fitBadgeClass(score) {
  if (score == null) return 'bg-muted text-muted-foreground border-transparent';
  if (score >= 70) return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30';
  if (score >= 40) return 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30';
  return 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30';
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-bounce"
          style={{ animationDelay: `${i * 120}ms` }}
        />
      ))}
    </div>
  );
}

function AddonResult({ addonKey, result, onCopy }) {
  if (addonKey === 'tailor') {
    return (
      <div className="space-y-3 text-sm">
        {result.ats_score != null && (
          <div><span className="text-muted-foreground">Estimated ATS match: </span><b>{result.ats_score}%</b></div>
        )}
        {result.tailoring_tips?.length > 0 && (
          <ul className="list-disc pl-4 space-y-1">
            {result.tailoring_tips.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        )}
        {result.cover_letter && (
          <div className="space-y-1.5">
            <Textarea readOnly value={result.cover_letter} rows={8} className="text-sm" />
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => onCopy(result.cover_letter, 'cover letter')}>
              <Copy className="h-3 w-3 mr-1.5" /> Copy cover letter
            </Button>
          </div>
        )}
      </div>
    );
  }
  if (addonKey === 'prep') {
    return (
      <div className="space-y-4 text-sm">
        {result.questions?.map((q, i) => (
          <div key={i} className="space-y-1">
            <div className="font-medium">{q.question}</div>
            {q.why_asked && <div className="text-muted-foreground italic text-xs">Why they ask: {q.why_asked}</div>}
            {q.model_answer && <div className="text-muted-foreground">{q.model_answer}</div>}
          </div>
        ))}
        {result.talking_points?.length > 0 && (
          <div>
            <div className="text-muted-foreground mb-1 text-xs">Talking points:</div>
            <ul className="list-disc pl-4 space-y-1">
              {result.talking_points.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          </div>
        )}
      </div>
    );
  }
  // salary
  return (
    <div className="space-y-3 text-sm">
      {result.suggested_range && (
        <div><span className="text-muted-foreground">Suggested range: </span><b>{result.suggested_range}</b></div>
      )}
      {result.negotiation_script && (
        <div className="space-y-1.5">
          <div className="text-muted-foreground text-xs">Negotiation script:</div>
          <Textarea readOnly value={result.negotiation_script} rows={4} className="text-sm" />
        </div>
      )}
      {result.key_points?.length > 0 && (
        <ul className="list-disc pl-4 space-y-1">
          {result.key_points.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      )}
    </div>
  );
}

export default function Pipeline() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const exchangedRef = useRef(false);

  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [gmailEmail, setGmailEmail] = useState('');
  const [googleClientId, setGoogleClientId] = useState('');

  const [profileDraft, setProfileDraft] = useState('');
  const [profileSaved, setProfileSaved] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);

  const [jobs, setJobs] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [digestEnabled, setDigestEnabled] = useState(false);
  const [applyingId, setApplyingId] = useState(null);

  // Per-job paid add-ons, fetched on demand and kept client-side (a repeat
  // click after a refresh just hits the backend's KB cache again — cheap).
  // Shape: { [jobId]: { tailor: {result, chat, input, sending}, prep: {...}, salary: {...}, loading: {tailor|prep|salary: bool} } }
  const [addons, setAddons] = useState({});
  // Which add-on's chat panel is open right now — { job, key } | null.
  const [activeAddon, setActiveAddon] = useState(null);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [statusRes, profileRes, pipelineRes, oauthRes] = await Promise.all([
        api.get('/career/gmail/status'),
        api.get('/career/profile'),
        api.get('/career/pipeline'),
        api.get('/auth/oauth-config'),
      ]);
      setConnected(!!statusRes.data.connected);
      setGmailEmail(statusRes.data.email || '');
      setProfileDraft(profileRes.data.profile_text || '');
      setProfileSaved(profileRes.data.profile_text || '');
      setDigestEnabled(!!profileRes.data.digest_enabled);
      setJobs(pipelineRes.data.items || []);
      setGoogleClientId(oauthRes.data?.google?.client_id || '');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to load Pipeline');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Guard against React StrictMode double-invocation replaying the
    // single-use Gmail auth code (same trick as AuthCallback.jsx).
    if (exchangedRef.current) return;
    exchangedRef.current = true;

    const code = params.get('code');
    const state = params.get('state');
    if (code && state === 'gmail_connect') {
      (async () => {
        setConnecting(true);
        try {
          const redirect_uri = `${window.location.origin}/career`;
          await api.post('/career/gmail/connect', { code, redirect_uri });
          toast.success('Gmail connected');
        } catch (e) {
          toast.error(e.response?.data?.detail || 'Gmail connection failed');
        } finally {
          setConnecting(false);
          navigate('/career', { replace: true });
          loadAll();
        }
      })();
    } else {
      loadAll();
    }
    // eslint-disable-next-line
  }, []);

  const connectGmail = () => {
    if (!googleClientId) { toast.error('Google OAuth is not configured on this server'); return; }
    const redirect_uri = `${window.location.origin}/career`;
    const url = 'https://accounts.google.com/o/oauth2/v2/auth?' + new URLSearchParams({
      client_id: googleClientId,
      redirect_uri,
      response_type: 'code',
      scope: 'https://www.googleapis.com/auth/gmail.readonly',
      access_type: 'offline',
      prompt: 'consent',
      state: 'gmail_connect',
    }).toString();
    window.location.href = url;
  };

  const disconnectGmail = async () => {
    try {
      await api.post('/career/gmail/disconnect');
      setConnected(false);
      setGmailEmail('');
      toast.success('Gmail disconnected');
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to disconnect'); }
  };

  const saveProfile = async () => {
    if (profileDraft.trim().length < 10) return toast.error('Add a bit more detail (at least 10 characters)');
    setSavingProfile(true);
    try {
      await api.post('/career/profile', { profile_text: profileDraft });
      setProfileSaved(profileDraft);
      toast.success('Profile saved');
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save profile'); }
    finally { setSavingProfile(false); }
  };

  const scan = async () => {
    setScanning(true);
    try {
      const { data } = await api.post('/career/pipeline/scan');
      const { data: list } = await api.get('/career/pipeline');
      setJobs(list.items || []);
      if (data.limited) {
        toast.warning(`Found ${data.new_count} new — stopped early, out of credits for this window.`);
      } else {
        toast.success(data.new_count > 0 ? `Found ${data.new_count} new job${data.new_count === 1 ? '' : 's'}` : 'No new job alerts since last scan');
      }
    } catch (e) { toast.error(e.response?.data?.detail || 'Scan failed'); }
    finally { setScanning(false); }
  };

  const discover = async () => {
    setDiscovering(true);
    try {
      const { data } = await api.post('/career/pipeline/discover');
      const { data: list } = await api.get('/career/pipeline');
      setJobs(list.items || []);
      if (data.limited) {
        toast.warning(`Found ${data.new_count} new — stopped early, out of credits for this window.`);
      } else {
        toast.success(data.new_count > 0 ? `Found ${data.new_count} new job${data.new_count === 1 ? '' : 's'} across job boards` : 'No new matches right now — try again later');
      }
    } catch (e) { toast.error(e.response?.data?.detail || 'Search failed'); }
    finally { setDiscovering(false); }
  };

  const toggleDigest = async (enabled) => {
    setDigestEnabled(enabled);
    try {
      await api.post('/career/digest/toggle', { enabled });
      toast.success(enabled ? 'Daily digest emails turned on' : 'Daily digest emails turned off');
    } catch (e) {
      setDigestEnabled(!enabled);
      toast.error(e.response?.data?.detail || 'Failed to update digest setting');
    }
  };

  const applyToJob = async (job) => {
    // Open the tab synchronously with the click so browsers don't treat it as
    // a blocked popup (that would happen if `window.open` only ran after the
    // `await` below resolves) — point it at the real URL once we have it.
    const win = window.open('', '_blank');
    if (win) win.opener = null;
    setApplyingId(job.id);
    try {
      const { data } = await api.post(`/career/pipeline/${job.id}/apply`);
      if (win) win.location.href = data.job_url; else window.open(data.job_url, '_blank', 'noopener,noreferrer');
      setJobs((cur) => cur.map((j) => (j.id === job.id ? { ...j, status: 'applied' } : j)));
    } catch (e) {
      if (win) win.close();
      toast.error(e.response?.data?.detail || 'Could not open this posting');
    } finally { setApplyingId(null); }
  };

  const updateStatus = async (jobId, status) => {
    const prev = jobs;
    setJobs((cur) => cur.map((j) => (j.id === jobId ? { ...j, status } : j)));
    try {
      await api.patch(`/career/pipeline/${jobId}/status`, { status });
    } catch (e) {
      setJobs(prev);
      toast.error(e.response?.data?.detail || 'Failed to update status');
    }
  };

  const copyOutreach = (text) => {
    navigator.clipboard?.writeText(text || '');
    toast.success('Copied outreach message');
  };

  const copyText = (text, label) => {
    navigator.clipboard?.writeText(text || '');
    toast.success(`Copied ${label}`);
  };

  // Fetches a result the first time (if not already cached client-side), then
  // opens the slide-over panel to show it plus its follow-up chat.
  const openAddon = async (job, key) => {
    const existing = addons[job.id]?.[key]?.result;
    if (existing) { setActiveAddon({ job, key }); return; }
    setAddons((cur) => ({
      ...cur,
      [job.id]: { ...cur[job.id], loading: { ...(cur[job.id]?.loading || {}), [key]: true } },
    }));
    try {
      const { data } = await api.post(`/career/pipeline/${job.id}/${ADDON_CONFIG[key].path}`);
      setAddons((cur) => ({
        ...cur,
        [job.id]: {
          ...cur[job.id],
          [key]: { result: data, chat: [], input: '', sending: false },
          loading: { ...(cur[job.id]?.loading || {}), [key]: false },
        },
      }));
      setActiveAddon({ job, key });
    } catch (e) {
      toast.error(e.response?.data?.detail || `${ADDON_CONFIG[key].label} failed`);
      setAddons((cur) => ({
        ...cur,
        [job.id]: { ...cur[job.id], loading: { ...(cur[job.id]?.loading || {}), [key]: false } },
      }));
    }
  };

  const setAddonChatInput = (jobId, key, value) => {
    setAddons((cur) => ({
      ...cur,
      [jobId]: { ...cur[jobId], [key]: { ...cur[jobId]?.[key], input: value } },
    }));
  };

  const sendAddonChat = async (jobId, key) => {
    const state = addons[jobId]?.[key];
    const text = (state?.input || '').trim();
    if (!text || state?.sending) return;
    const priorHistory = state.chat || [];
    const newHistory = [...priorHistory, { role: 'user', content: text }];
    setAddons((cur) => ({
      ...cur,
      [jobId]: { ...cur[jobId], [key]: { ...cur[jobId][key], chat: newHistory, input: '', sending: true } },
    }));
    try {
      const { data } = await api.post(`/career/pipeline/${jobId}/${ADDON_CONFIG[key].path}/chat`, {
        message: text,
        context: state.result,
        history: priorHistory,
      });
      setAddons((cur) => ({
        ...cur,
        [jobId]: {
          ...cur[jobId],
          [key]: { ...cur[jobId][key], chat: [...newHistory, { role: 'assistant', content: data.reply }], sending: false },
        },
      }));
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Follow-up failed');
      setAddons((cur) => ({
        ...cur,
        [jobId]: { ...cur[jobId], [key]: { ...cur[jobId][key], sending: false } },
      }));
    }
  };

  const profileDirty = profileDraft !== profileSaved;
  const activeState = activeAddon ? addons[activeAddon.job.id]?.[activeAddon.key] : null;
  const activeCfg = activeAddon ? ADDON_CONFIG[activeAddon.key] : null;

  if (loading) {
    return (
      <div className="mt-16 flex justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mt-6 space-y-4" data-testid="career-pipeline">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Mail className="h-4 w-4 text-primary" />
            Gmail
          </div>
          {connected ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">{gmailEmail}</span>
              <Button variant="outline" size="sm" onClick={disconnectGmail}>Disconnect</Button>
            </div>
          ) : (
            <Button size="sm" onClick={connectGmail} disabled={connecting}>
              {connecting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Mail className="h-4 w-4 mr-2" />}
              Connect Gmail
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Reads LinkedIn job-alert emails from this Gmail account only, on-demand. Nothing is sent or read automatically in the background.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Search className="h-4 w-4 text-primary" />
            Search job boards
          </div>
          <Button
            data-testid="career-pipeline-discover-btn"
            size="sm"
            onClick={discover}
            disabled={discovering || !profileSaved.trim()}
          >
            {discovering ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
            Find matching jobs now
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Searches LinkedIn, Naukri, Indeed and TimesJobs directly using your profile below — no LinkedIn account or job-alert subscription needed.
        </p>
        <div className="flex items-center justify-between pt-2 border-t border-border">
          <div>
            <div className="text-sm">Email me a daily digest</div>
            <div className="text-xs text-muted-foreground">One email a day if new matching jobs show up.</div>
          </div>
          <Switch checked={digestEnabled} onCheckedChange={toggleDigest} disabled={!profileSaved.trim()} />
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="text-sm font-medium">Your profile</div>
        <Textarea
          data-testid="career-pipeline-profile"
          value={profileDraft}
          onChange={(e) => setProfileDraft(e.target.value)}
          placeholder="Paste a short resume summary or target-role blurb — used to score each job's fit and draft outreach."
          rows={4}
        />
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={saveProfile} disabled={savingProfile || !profileDirty}>
            {savingProfile ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
            Save profile
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-muted-foreground">{jobs.length} job{jobs.length === 1 ? '' : 's'} tracked</div>
        <Button
          data-testid="career-pipeline-scan-btn"
          onClick={scan}
          disabled={scanning || !connected || !profileSaved.trim()}
        >
          {scanning ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
          Scan for new jobs
        </Button>
      </div>

      <div className="space-y-3" data-testid="career-pipeline-results">
        {jobs.map((j) => (
          <div
            key={j.id}
            className="rounded-lg border border-border bg-card p-4 animate-in fade-in slide-in-from-bottom-2 duration-300 transition-shadow hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium">{j.title}</span>
                  <Badge className={`${fitBadgeClass(j.fit_score)} animate-in zoom-in-75 duration-300`}>
                    {j.fit_score != null ? `${j.fit_score}% fit` : 'unscored'}
                  </Badge>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                  {j.company && <span>{j.company}</span>}
                  {j.location && <span className="flex items-center gap-1"><MapPin className="h-3 w-3" />{j.location}</span>}
                  {j.job_url && (
                    <a href={j.job_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-primary hover:underline">
                      View posting <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={applyingId === j.id || !j.job_url}
                  onClick={() => applyToJob(j)}
                >
                  {applyingId === j.id ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Send className="h-3.5 w-3.5 mr-1.5" />}
                  Apply
                </Button>
                <Select value={j.status} onValueChange={(v) => updateStatus(j.id, v)}>
                  <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {STATUS_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {j.fit_reason && <p className="mt-3 text-sm text-muted-foreground">{j.fit_reason}</p>}

            <Collapsible className="mt-3">
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground">
                  <Users className="h-3.5 w-3.5 mr-1.5" />
                  Recruiter outreach
                  <ChevronDown className="h-3.5 w-3.5 ml-1.5" />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-2 space-y-2 rounded-md bg-muted/40 p-3">
                {j.recruiter_title && (
                  <div className="text-xs"><span className="text-muted-foreground">Likely title: </span>{j.recruiter_title}</div>
                )}
                {j.linkedin_search_query && (
                  <div className="text-xs"><span className="text-muted-foreground">Search on LinkedIn: </span>{j.linkedin_search_query}</div>
                )}
                {j.outreach_message && (
                  <div className="space-y-1">
                    <Textarea readOnly value={j.outreach_message} rows={3} className="text-xs" />
                    <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => copyOutreach(j.outreach_message)}>
                      <Copy className="h-3 w-3 mr-1.5" /> Copy
                    </Button>
                  </div>
                )}
              </CollapsibleContent>
            </Collapsible>

            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(ADDON_CONFIG).map(([key, cfg]) => {
                const jobAddon = addons[j.id];
                const loadingThis = jobAddon?.loading?.[key];
                const hasResult = !!jobAddon?.[key]?.result;
                const Icon = cfg.icon;
                return (
                  <Button
                    key={key}
                    variant="ghost"
                    size="sm"
                    className={`h-7 px-2 text-xs text-muted-foreground transition-all hover:scale-105 ${ACCENT[cfg.accent].hover}`}
                    disabled={loadingThis}
                    onClick={() => openAddon(j, key)}
                  >
                    {loadingThis ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Icon className="h-3.5 w-3.5 mr-1.5" />}
                    {cfg.label}
                    {hasResult && <span className={`ml-1.5 h-1.5 w-1.5 rounded-full ${ACCENT[cfg.accent].dot}`} />}
                  </Button>
                );
              })}
            </div>
          </div>
        ))}
        {jobs.length === 0 && (
          <div className="text-sm text-muted-foreground py-8 text-center">
            {profileSaved.trim()
              ? 'No jobs yet — click "Find matching jobs now" or "Scan for new jobs".'
              : 'Add a profile summary below, then search job boards or connect Gmail to get started.'}
          </div>
        )}
      </div>

      <Sheet open={!!activeAddon} onOpenChange={(open) => !open && setActiveAddon(null)}>
        <SheetContent side="right" className="w-full sm:max-w-lg p-0 flex flex-col gap-0">
          {activeAddon && (
            <>
              <SheetHeader className={`p-4 border-b border-border ${ACCENT[activeCfg.accent].border}`}>
                <SheetTitle>{activeCfg.label}</SheetTitle>
                <SheetDescription>
                  {activeAddon.job.title}{activeAddon.job.company ? ` · ${activeAddon.job.company}` : ''}
                </SheetDescription>
              </SheetHeader>

              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {activeState?.result && (
                  <AddonResult addonKey={activeAddon.key} result={activeState.result} onCopy={copyText} />
                )}

                {activeState?.chat?.length > 0 && (
                  <div className="space-y-2 pt-3 border-t border-border/60">
                    {activeState.chat.map((m, i) => (
                      <div
                        key={i}
                        className={`animate-in fade-in slide-in-from-bottom-1 duration-200 text-sm rounded-lg px-3 py-2 max-w-[85%] ${
                          m.role === 'user' ? 'ml-auto bg-primary text-primary-foreground' : 'bg-muted text-foreground'
                        }`}
                      >
                        {m.content}
                      </div>
                    ))}
                    {activeState.sending && (
                      <div className="bg-muted rounded-lg px-3 py-2 w-fit"><TypingDots /></div>
                    )}
                  </div>
                )}
              </div>

              <div className="border-t border-border p-3 flex items-center gap-2">
                <Input
                  value={activeState?.input || ''}
                  onChange={(e) => setAddonChatInput(activeAddon.job.id, activeAddon.key, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      sendAddonChat(activeAddon.job.id, activeAddon.key);
                    }
                  }}
                  placeholder="Ask a follow-up or push back on this…"
                  className="h-9 text-sm"
                />
                <Button
                  size="sm"
                  className="h-9 px-3"
                  disabled={activeState?.sending || !(activeState?.input || '').trim()}
                  onClick={() => sendAddonChat(activeAddon.job.id, activeAddon.key)}
                >
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
