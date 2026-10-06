import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { AnimatePresence, motion } from 'framer-motion';
import * as faceapi from 'face-api.js';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Slider } from '@/components/ui/slider';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle,
  AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import {
  Loader2, Upload, FileText, X, Mic, Video, Maximize, CheckCircle2, XCircle,
  ShieldAlert, ArrowRight, ArrowLeft, Package, Wifi, WifiOff, RefreshCw,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  detailToString, TOPIC_META, SENIORITY_LABEL, LANGUAGE_LABEL, humanize, summarizePackConfig,
  MIN_TECHNICAL_MINUTES, MAX_TECHNICAL_MINUTES, MIN_BEHAVIORAL_MINUTES, MAX_BEHAVIORAL_MINUTES,
} from './interviewUtils';

const MIN_RESUME_CHARS = 200;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const NET_PING_COUNT = 3;
const NET_GOOD_MS = 400;        // avg round-trip below this -> "Good"
const NET_RECHECK_MS = 10000;   // re-ping periodically while sitting on this step

// Sentinel local-only "grant" id for the admin no-pack testing bypass (see
// services/interview_service.create_session's docstring on the backend side)
// — never sent to the server as-is; startInterview() translates it to a real
// `grant_id: null` in the request body, which the backend only accepts from
// an admin. Using a distinct sentinel (not `null` itself) here, rather than
// reusing `null`, keeps the "selected grant changed" effect below firing
// correctly even when there's exactly one (synthetic) option to auto-select.
const ADMIN_BYPASS_GRANT_ID = '__admin_bypass__';
const ADMIN_BYPASS_CONFIG = {
  technical_minutes: 45, behavioral_minutes: 15,
  topics: ['dsa', 'hld', 'lld', 'design', 'hr'],
  seniority_levels: ['entry', 'mid', 'senior'],
  languages: ['python', 'javascript', 'cpp', 'java'],
  sub_topics: {},
};

export default function InterviewSetup() {
  const navigate = useNavigate();
  const isAdmin = useSelector((s) => s.auth.user?.role === 'admin');

  // ---- Entitlement grants — each is a distinct purchased pack "format"
  // (its own snapshotted technical/behavioral minutes, allowed topics,
  // seniority levels, languages, sub-topics). If the candidate owns more
  // than one, they choose which to spend in a dedicated first step;
  // otherwise it's auto-selected and that step is skipped entirely. An admin
  // with zero owned grants gets a synthetic full-bounds "grant" instead of
  // being sent back to the paywall — see ADMIN_BYPASS_GRANT_ID above. ------
  const [grants, setGrants] = useState(null); // null = loading
  const [selectedGrantId, setSelectedGrantId] = useState(null);
  const selectedGrant = grants?.find((g) => g.grant_id === selectedGrantId) || null;
  const config = selectedGrant?.config || {};

  const steps = useMemo(
    () => ((grants?.length || 0) > 1 ? ['Pack', 'Topic', 'Resume', 'System check', 'Instructions'] : ['Topic', 'Resume', 'System check', 'Instructions']),
    [grants],
  );
  const [step, setStep] = useState(0);
  const stepName = steps[step];
  const [creating, setCreating] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  // Mandatory acknowledgment gate on the Instructions step — the final
  // "Continue" button (and thus the fullscreen-triggering confirm dialog)
  // stays disabled until this is checked. See that step's render block.
  const [instructionsAck, setInstructionsAck] = useState(false);

  // ---- Topic step: topic + seniority + optional sub-topic/language/behavioral ----
  const [topic, setTopic] = useState(null);
  const [seniority, setSeniority] = useState(null);
  const [subTopic, setSubTopic] = useState(null);
  const [language, setLanguage] = useState(null);
  const [includeBehavioral, setIncludeBehavioral] = useState(true);
  // Candidate-adjustable duration — defaults come from the selected grant's
  // config but can be shortened/lengthened to fit an actual available time
  // slot (e.g. only have 15 minutes -> don't get forced into a 45-min round
  // you'll have to abandon halfway). Bounded server-side too; these mirror
  // the backend's MIN/MAX_*_MINUTES for slider ranges.
  const [technicalMinutes, setTechnicalMinutes] = useState(45);
  const [behavioralMinutes, setBehavioralMinutes] = useState(15);

  // ---- Resume step ----
  const [profile, setProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [useUpload, setUseUpload] = useState(false);
  const [file, setFile] = useState(null);
  const [pasted, setPasted] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const fileRef = useRef(null);

  // ---- System-check step ----
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const micBarRef = useRef(null);
  const rafRef = useRef(null);
  const [camError, setCamError] = useState('');
  const [faceDetected, setFaceDetected] = useState(false);
  const [checkingReady, setCheckingReady] = useState(true);
  const fullscreenSupported = typeof document !== 'undefined' && !!document.fullscreenEnabled;
  // 'checking' | 'good' | 'slow' | 'down'
  const [netStatus, setNetStatus] = useState('checking');
  const [netLatencyMs, setNetLatencyMs] = useState(null);

  // Load entitlement grants once; auto-select the sole grant if there's only
  // one. An admin with zero owned grants gets the synthetic bypass "grant"
  // instead of being bounced back to the paywall — everyone else still needs
  // a real pack.
  useEffect(() => {
    api.get('/interview/entitlement')
      .then((r) => {
        const g = r.data.grants || [];
        if (g.length === 0 && isAdmin) {
          const bypass = {
            grant_id: ADMIN_BYPASS_GRANT_ID, pack_name: 'Admin test mode (no pack)',
            sessions_remaining: null, sessions_total: null, config: ADMIN_BYPASS_CONFIG,
          };
          setGrants([bypass]);
          setSelectedGrantId(ADMIN_BYPASS_GRANT_ID);
          return;
        }
        setGrants(g);
        if (g.length === 0) {
          toast.error('No Mock Interview sessions remaining — buy a pack first.');
          navigate('/interview');
        } else if (g.length === 1) {
          setSelectedGrantId(g[0].grant_id);
        }
      })
      .catch((e) => {
        toast.error(detailToString(e, 'Failed to load your interview packs'));
        navigate('/interview');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset the fine-grained choices whenever the selected grant changes (its
  // config bounds are what these choices are validated/filtered against),
  // seeding sensible defaults from that grant's config.
  useEffect(() => {
    if (!selectedGrant) return;
    const cfg = selectedGrant.config || {};
    setTopic((prev) => (cfg.topics?.includes(prev) ? prev : cfg.topics?.[0] || null));
    setSeniority((prev) => (cfg.seniority_levels?.includes(prev) ? prev : cfg.seniority_levels?.[0] || null));
    setIncludeBehavioral((cfg.behavioral_minutes || 0) > 0);
    setSubTopic(null);
    setLanguage(cfg.languages?.[0] || null);
    setTechnicalMinutes(cfg.technical_minutes || 45);
    setBehavioralMinutes(cfg.behavioral_minutes > 0 ? cfg.behavioral_minutes : 15);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGrantId]);

  // When the topic changes, drop a sub-topic that no longer applies.
  useEffect(() => {
    const allowed = (config.sub_topics || {})[topic] || [];
    if (subTopic && !allowed.includes(subTopic)) setSubTopic(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topic]);

  useEffect(() => {
    api.get('/resume/profile')
      .then((r) => setProfile(r.data.profile))
      .catch(() => {})
      .finally(() => setProfileLoading(false));
  }, []);

  // Acquire camera+mic once we reach the system-check step; release on unmount
  // or when leaving the wizard. This is the ONE getUserMedia call for setup —
  // the live session (InterviewSession.jsx) opens its own on entry.
  useEffect(() => {
    if (stepName !== 'System check') return undefined;
    let cancelled = false;
    (async () => {
      setCheckingReady(true);
      setCamError('');
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;

        // Mic level meter
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        const data = new Uint8Array(analyser.fftSize);
        const tick = () => {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
          const level = Math.min(1, Math.sqrt(sum / data.length) * 4);
          if (micBarRef.current) micBarRef.current.style.width = `${Math.round(level * 100)}%`;
          rafRef.current = requestAnimationFrame(tick);
        };
        tick();

        // Face detection (same TinyFaceDetector model the live session's
        // proctoring hook uses) — here it's purely informational.
        try {
          await faceapi.nets.tinyFaceDetector.loadFromUri('/models');
          const detectLoop = setInterval(async () => {
            if (!videoRef.current || videoRef.current.readyState < 2) return;
            try {
              const detections = await faceapi.detectAllFaces(
                videoRef.current, new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 }),
              );
              setFaceDetected(detections.length === 1);
            } catch { /* ignore a bad frame */ }
          }, 1000);
          streamRef.current._detectLoop = detectLoop;
        } catch {
          // model failed to load — system check still passes on cam/mic alone
        }

        setCheckingReady(false);
      } catch (e) {
        setCamError(e?.message || 'Could not access camera/microphone. Check browser permissions.');
        setCheckingReady(false);
      }
    })();

    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (streamRef.current) {
        if (streamRef.current._detectLoop) clearInterval(streamRef.current._detectLoop);
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
    };
  }, [stepName]);

  // Network check — pings the API's lightweight /health endpoint (no auth,
  // no DB work) a few times and classifies by average round-trip latency.
  // Re-checks periodically while the candidate sits on this step, since a
  // connection that looked fine a minute ago can degrade before they
  // actually start. A failed/timed-out ping means "down," not just "slow."
  const runNetworkCheck = async () => {
    setNetStatus('checking');
    const samples = [];
    for (let i = 0; i < NET_PING_COUNT; i++) {
      const started = performance.now();
      try {
        await api.get('/health', { timeout: 5000 });
        samples.push(performance.now() - started);
      } catch {
        // one failed ping doesn't necessarily mean "down" — only classify
        // as down if EVERY attempt failed (see below)
      }
    }
    if (samples.length === 0) {
      setNetStatus('down');
      setNetLatencyMs(null);
      return;
    }
    const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
    setNetLatencyMs(Math.round(avg));
    setNetStatus(avg <= NET_GOOD_MS ? 'good' : 'slow');
  };

  useEffect(() => {
    if (stepName !== 'System check') return undefined;
    runNetworkCheck();
    const id = setInterval(runNetworkCheck, NET_RECHECK_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepName]);

  const pickFile = (f) => {
    if (!f) return;
    if (f.size > MAX_FILE_BYTES) return toast.error('File too large. Max 5MB.');
    setFile(f);
    setPasted('');
  };

  const saveProfile = async () => {
    if (!file && pasted.trim().length < MIN_RESUME_CHARS) {
      toast.error(`Upload a resume or paste at least ${MIN_RESUME_CHARS} characters.`);
      return;
    }
    setSavingProfile(true);
    try {
      const form = new FormData();
      if (file) form.append('file', file);
      else form.append('resume_text', pasted);
      const { data } = await api.post('/resume/profile', form);
      setProfile(data.profile);
      setUseUpload(false);
      toast.success('Resume linked');
    } catch (e) {
      toast.error(detailToString(e, 'Failed to save resume'));
    } finally {
      setSavingProfile(false);
    }
  };

  const canProceed = () => {
    if (stepName === 'Pack') return !!selectedGrantId;
    if (stepName === 'Topic') return !!topic && !!seniority;
    // System check genuinely gates progress — there's no point entering a
    // proctored, voice-driven interview with no camera/mic access or no
    // reachable server. "Slow" network and "no face detected" are
    // advisory-only (lighting/angle/connection quality vary too much to
    // hard-block on), but a flat-out failure on either doesn't.
    if (stepName === 'System check') return !camError && netStatus !== 'down' && netStatus !== 'checking';
    return true;
  };

  const isDsaTopic = topic === 'dsa';
  const subTopicOptions = (config.sub_topics || {})[topic] || [];
  const hasBehavioralOption = (config.behavioral_minutes || 0) > 0;

  const startInterview = async () => {
    setCreating(true);
    try {
      const body = {
        grant_id: selectedGrantId === ADMIN_BYPASS_GRANT_ID ? null : selectedGrantId,
        topic,
        seniority,
        resume_profile_id: profile?.id,
        technical_minutes: technicalMinutes,
      };
      if (subTopic) body.sub_topic = subTopic;
      if (isDsaTopic && language) body.language = language;
      if (hasBehavioralOption) {
        body.include_behavioral = includeBehavioral;
        if (includeBehavioral) body.behavioral_minutes = behavioralMinutes;
      }
      const { data } = await api.post('/interview/sessions', body);
      setConsentOpen(false);
      navigate(`/interview/${data.id}`, { state: { language: isDsaTopic ? language : null } });
    } catch (e) {
      toast.error(detailToString(e, 'Failed to start interview'));
      setCreating(false);
    }
  };

  // The fullscreen request MUST happen synchronously inside this click
  // handler (a real user gesture) — calling it after an awaited API call
  // would lose transient activation in most browsers.
  const confirmAndStart = () => {
    const el = document.documentElement;
    if (el.requestFullscreen) el.requestFullscreen().catch(() => {});
    startInterview();
  };

  return (
    <div className="max-w-3xl mx-auto p-6" data-testid="interview-setup-page">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-semibold tracking-tight">Set up your mock interview</h1>
        {selectedGrantId === ADMIN_BYPASS_GRANT_ID && (
          <Badge variant="outline" className="mt-2 text-amber-500 border-amber-500/30" data-testid="interview-admin-bypass-badge">
            Admin test mode — no pack consumed
          </Badge>
        )}
        {grants === null ? (
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading your interview packs…
          </div>
        ) : (
          <>
            <div className="mt-4 flex items-center gap-2">
              {steps.map((s, i) => (
                <div key={s} className="flex items-center gap-2 flex-1">
                  <div className={`h-1.5 flex-1 rounded-full ${i <= step ? 'bg-primary' : 'bg-muted'}`} />
                </div>
              ))}
            </div>
            <div className="mt-1.5 text-xs text-muted-foreground">Step {step + 1} of {steps.length}: {stepName}</div>
          </>
        )}
      </div>

      {grants !== null && (
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -16 }}
          transition={{ duration: 0.25 }}
        >
          {stepName === 'Pack' && (
            <div className="space-y-3" data-testid="interview-step-pack">
              <div className="text-sm font-medium mb-1">Which pack would you like to use?</div>
              <p className="text-xs text-muted-foreground mb-3">You own sessions across more than one interview pack format.</p>
              {grants.map((g) => (
                <button
                  key={g.grant_id}
                  type="button"
                  onClick={() => setSelectedGrantId(g.grant_id)}
                  data-testid={`interview-grant-${g.grant_id}`}
                  className={`w-full text-left rounded-xl border p-4 transition-colors flex items-center gap-3 ${selectedGrantId === g.grant_id ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40'}`}
                >
                  <Package className="h-5 w-5 text-primary shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium flex items-center gap-2">
                      {g.pack_name}
                      <Badge variant="outline" className="text-[10px]">{g.sessions_remaining}/{g.sessions_total} left</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">{summarizePackConfig(g.config)}</div>
                  </div>
                  {selectedGrantId === g.grant_id && <CheckCircle2 className="h-4 w-4 text-primary shrink-0" />}
                </button>
              ))}
            </div>
          )}

          {stepName === 'Topic' && (
            <div className="space-y-6" data-testid="interview-step-topic">
              <div>
                <div className="text-sm font-medium mb-3">Choose a round type</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {(config.topics || []).map((key) => {
                    const meta = TOPIC_META[key] || { label: humanize(key), desc: '' };
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setTopic(key)}
                        data-testid={`interview-topic-${key}`}
                        className={`text-left rounded-xl border p-4 transition-colors ${topic === key ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40'}`}
                      >
                        <div className="font-medium flex items-center justify-between">
                          {meta.label}
                          {topic === key && <CheckCircle2 className="h-4 w-4 text-primary" />}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{meta.desc}</div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {subTopicOptions.length > 0 && (
                <div data-testid="interview-subtopic-picker">
                  <div className="text-sm font-medium mb-2">Focus area <span className="text-xs text-muted-foreground font-normal">(optional)</span></div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setSubTopic(null)}
                      className={`text-xs rounded-full px-3 py-1.5 border transition-colors ${!subTopic ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:border-primary/40'}`}
                    >
                      No preference
                    </button>
                    {subTopicOptions.map((st) => (
                      <button
                        key={st}
                        type="button"
                        onClick={() => setSubTopic(st)}
                        data-testid={`interview-subtopic-${st}`}
                        className={`text-xs rounded-full px-3 py-1.5 border transition-colors ${subTopic === st ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:border-primary/40'}`}
                      >
                        {humanize(st)}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium mb-2">Seniority</div>
                  <Select value={seniority ?? undefined} onValueChange={setSeniority}>
                    <SelectTrigger className="w-full sm:w-56" data-testid="interview-seniority-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {(config.seniority_levels || []).map((v) => (
                        <SelectItem key={v} value={v}>{SENIORITY_LABEL[v] || humanize(v)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {isDsaTopic && (config.languages || []).length > 0 && (
                  <div data-testid="interview-language-picker">
                    <div className="text-sm font-medium mb-2">Coding language</div>
                    <Select value={language ?? undefined} onValueChange={setLanguage}>
                      <SelectTrigger className="w-full sm:w-56" data-testid="interview-language-select"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(config.languages || []).map((v) => (
                          <SelectItem key={v} value={v}>{LANGUAGE_LABEL[v] || humanize(v)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>

              {hasBehavioralOption && (
                <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4" data-testid="interview-behavioral-toggle">
                  <div>
                    <div className="text-sm font-medium">Include behavioral round</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      Adds an HR/behavioral segment after the technical round.
                    </div>
                  </div>
                  <Switch checked={includeBehavioral} onCheckedChange={setIncludeBehavioral} />
                </div>
              )}

              <div className="rounded-lg border border-border bg-card p-4 space-y-5" data-testid="interview-duration-picker">
                <div>
                  <div className="text-xs text-muted-foreground mb-3">
                    Default is {config.technical_minutes}
                    {config.behavioral_minutes > 0 ? `+${config.behavioral_minutes}` : ''} min — adjust to fit your schedule
                    (e.g. only have 15 minutes? Shorten it below instead of leaving the interview halfway).
                  </div>
                </div>
                <div>
                  <div className="flex items-baseline justify-between mb-2">
                    <span className="text-sm font-medium">Technical round</span>
                    <span className="text-sm font-mono text-primary" data-testid="interview-technical-minutes-value">{technicalMinutes} min</span>
                  </div>
                  <Slider
                    value={[technicalMinutes]}
                    min={MIN_TECHNICAL_MINUTES} max={MAX_TECHNICAL_MINUTES} step={5}
                    onValueChange={([v]) => setTechnicalMinutes(v)}
                    data-testid="interview-technical-minutes-slider"
                  />
                  <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                    <span>{MIN_TECHNICAL_MINUTES} min</span>
                    <span>{MAX_TECHNICAL_MINUTES} min</span>
                  </div>
                </div>
                {includeBehavioral && (
                  <div>
                    <div className="flex items-baseline justify-between mb-2">
                      <span className="text-sm font-medium">Behavioral round</span>
                      <span className="text-sm font-mono text-primary" data-testid="interview-behavioral-minutes-value">{behavioralMinutes} min</span>
                    </div>
                    <Slider
                      value={[behavioralMinutes]}
                      min={MIN_BEHAVIORAL_MINUTES} max={MAX_BEHAVIORAL_MINUTES} step={5}
                      onValueChange={([v]) => setBehavioralMinutes(v)}
                      data-testid="interview-behavioral-minutes-slider"
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                      <span>{MIN_BEHAVIORAL_MINUTES} min</span>
                      <span>{MAX_BEHAVIORAL_MINUTES} min</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {stepName === 'Resume' && (
            <div className="space-y-4" data-testid="interview-step-resume">
              {profileLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
                  <Loader2 className="h-4 w-4 animate-spin" /> Checking for an existing resume…
                </div>
              ) : profile && !useUpload ? (
                <div className="rounded-lg border border-border bg-card p-5" data-testid="interview-resume-existing">
                  <div className="flex items-center gap-2 font-medium"><FileText className="h-4 w-4 text-primary" /> Resume on file</div>
                  <div className="text-sm text-muted-foreground mt-2">
                    {profile.filename || 'Pasted resume text'} · ATS score {profile.ats_score ?? '—'} · updated {profile.updated_at ? new Date(profile.updated_at).toLocaleDateString() : '—'}
                  </div>
                  {profile.structured?.skills?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      {profile.structured.skills.slice(0, 10).map((s) => (
                        <span key={s} className="text-xs rounded-full bg-muted px-2 py-0.5">{s}</span>
                      ))}
                    </div>
                  )}
                  <Button variant="outline" size="sm" className="mt-4" onClick={() => setUseUpload(true)} data-testid="interview-resume-change-btn">
                    Upload a different resume
                  </Button>
                </div>
              ) : (
                <div className="rounded-lg border border-border bg-card p-5 space-y-3" data-testid="interview-resume-upload">
                  <div className="flex items-center gap-2">
                    <input
                      ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden"
                      onChange={(e) => pickFile(e.target.files?.[0])} data-testid="interview-resume-file-input"
                    />
                    <Button variant="outline" onClick={() => fileRef.current?.click()}>
                      <Upload className="h-4 w-4 mr-2" /> {file ? 'Change file' : 'Upload resume'}
                    </Button>
                    {file ? (
                      <span className="flex items-center gap-2 text-sm text-muted-foreground min-w-0">
                        <FileText className="h-4 w-4 flex-shrink-0" /><span className="truncate">{file.name}</span>
                        <button onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ''; }} aria-label="Remove file">
                          <X className="h-4 w-4" />
                        </button>
                      </span>
                    ) : <span className="text-xs text-muted-foreground">PDF, DOCX or TXT · max 5MB</span>}
                  </div>
                  {!file && (
                    <Textarea
                      value={pasted} onChange={(e) => setPasted(e.target.value)} rows={6}
                      placeholder={`…or paste your resume text here (at least ${MIN_RESUME_CHARS} characters)`}
                      data-testid="interview-resume-paste"
                    />
                  )}
                  <div className="flex items-center gap-2">
                    <Button onClick={saveProfile} disabled={savingProfile} data-testid="interview-resume-save-btn">
                      {savingProfile ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null} Save resume
                    </Button>
                    {profile && <Button variant="ghost" onClick={() => setUseUpload(false)}>Cancel</Button>}
                  </div>
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                Optional — linking a resume lets the interviewer tailor questions to your background. You can skip this.
              </p>
            </div>
          )}

          {stepName === 'System check' && (
            <div className="space-y-4" data-testid="interview-step-check">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="rounded-lg border border-border bg-card overflow-hidden">
                  <video ref={videoRef} autoPlay muted playsInline className="w-full aspect-video object-cover -scale-x-100 bg-black" />
                  <div className="p-3 flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 text-muted-foreground"><Video className="h-3.5 w-3.5" /> Camera</span>
                    {checkingReady ? (
                      <span className="text-muted-foreground">Checking…</span>
                    ) : faceDetected ? (
                      <span className="flex items-center gap-1 text-emerald-500"><CheckCircle2 className="h-3.5 w-3.5" /> Face detected</span>
                    ) : (
                      <span className="flex items-center gap-1 text-amber-500"><XCircle className="h-3.5 w-3.5" /> No face detected</span>
                    )}
                  </div>
                </div>
                <div className="space-y-4">
                  <div className="rounded-lg border border-border bg-card p-4">
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2"><Mic className="h-3.5 w-3.5" /> Microphone level</div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div ref={micBarRef} className="h-full bg-primary transition-[width] duration-75" style={{ width: '0%' }} />
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-2">Speak normally — the bar should move.</p>
                  </div>
                  <div className="rounded-lg border border-border bg-card p-4" data-testid="interview-network-check">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        {netStatus === 'down' ? <WifiOff className="h-3.5 w-3.5" /> : <Wifi className="h-3.5 w-3.5" />} Network
                      </span>
                      {netStatus === 'checking' ? (
                        <span className="flex items-center gap-1 text-muted-foreground text-xs"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking…</span>
                      ) : netStatus === 'good' ? (
                        <span className="flex items-center gap-1 text-emerald-500 text-xs"><CheckCircle2 className="h-3.5 w-3.5" /> Good · {netLatencyMs}ms</span>
                      ) : netStatus === 'slow' ? (
                        <span className="flex items-center gap-1 text-amber-500 text-xs"><XCircle className="h-3.5 w-3.5" /> Slow · {netLatencyMs}ms</span>
                      ) : (
                        <span className="flex items-center gap-1 text-destructive text-xs"><XCircle className="h-3.5 w-3.5" /> Unreachable</span>
                      )}
                    </div>
                    {netStatus === 'slow' && (
                      <p className="text-[11px] text-amber-500/90 mt-2">Your connection is slow — voice responses may take longer to process than usual.</p>
                    )}
                    {netStatus === 'down' && (
                      <div className="flex items-center justify-between mt-2">
                        <p className="text-[11px] text-destructive">Can't reach the server. Check your connection and retry.</p>
                        <Button size="sm" variant="outline" onClick={runNetworkCheck} data-testid="interview-network-retry-btn">
                          <RefreshCw className="h-3 w-3 mr-1.5" /> Retry
                        </Button>
                      </div>
                    )}
                  </div>
                  <div className="rounded-lg border border-border bg-card p-4 flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Maximize className="h-3.5 w-3.5" /> Fullscreen support</span>
                    {fullscreenSupported ? (
                      <span className="flex items-center gap-1 text-emerald-500 text-xs"><CheckCircle2 className="h-3.5 w-3.5" /> Supported</span>
                    ) : (
                      <span className="flex items-center gap-1 text-destructive text-xs"><XCircle className="h-3.5 w-3.5" /> Not supported</span>
                    )}
                  </div>
                  {camError && (
                    <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">{camError}</div>
                  )}
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Your camera and mic are used only for proctoring and voice answers during the interview — nothing is recorded continuously.
              </p>
            </div>
          )}

          {stepName === 'Instructions' && (
            <div className="space-y-5" data-testid="interview-step-consent">
              <div className="rounded-xl border border-border bg-card p-6 space-y-5">
                <div className="flex items-center gap-2">
                  <ShieldAlert className="h-5 w-5 text-primary" />
                  <h2 className="font-display text-xl font-medium">Before you begin — please read carefully</h2>
                </div>

                <div>
                  <div className="text-sm font-medium mb-1.5">Your session</div>
                  <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                    <li>
                      Topic: {TOPIC_META[topic]?.label || humanize(topic)}
                      {subTopic ? ` — focus: ${humanize(subTopic)}` : ''}, Seniority: {SENIORITY_LABEL[seniority] || humanize(seniority)}
                    </li>
                    <li>
                      Technical round: {technicalMinutes} minutes
                      {includeBehavioral ? `, then a ${behavioralMinutes}-minute behavioral round` : ' (no behavioral round for this session)'}.
                    </li>
                    <li>The interviewer greets you and asks the first question automatically — you don't need to speak first.</li>
                  </ul>
                </div>

                <div>
                  <div className="text-sm font-medium mb-1.5">How to answer</div>
                  <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                    <li>Click the mic once to start answering, click it again when you're done — or use "Type instead" for a typed answer.</li>
                    {isDsaTopic && <li>For coding questions, write your solution in the code editor and click "Discuss this code."</li>}
                    <li>Each answer takes a few seconds to process (transcription + thinking) — that's normal, not a freeze.</li>
                  </ul>
                </div>

                <div>
                  <div className="text-sm font-medium mb-1.5 text-destructive">Proctoring — read this closely</div>
                  <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                    <li>The session runs in fullscreen with your camera on for the entire interview.</li>
                    <li>Your face must stay visible in frame — no one else should enter the shot.</li>
                    <li>Do not exit fullscreen, switch tabs/apps, or use another device to look up answers.</li>
                    <li>Do not copy or paste text during the session.</li>
                    <li><strong className="text-foreground">You get 2 warnings. A 3rd confirmed violation ends the interview immediately</strong> — no exceptions, and it can't be undone.</li>
                    <li>Short clips are captured only around a flagged moment — never a continuous recording.</li>
                  </ul>
                </div>

                <div>
                  <div className="text-sm font-medium mb-1.5">When you're done</div>
                  <p className="text-sm text-muted-foreground">
                    You'll get a full analysis report — score breakdown, strengths, areas to improve — and a summary is added to your Career Intelligence profile.
                  </p>
                </div>
              </div>

              <label
                className={`flex items-start gap-3 rounded-lg border p-4 cursor-pointer transition-colors ${instructionsAck ? 'border-primary bg-primary/5' : 'border-border bg-card'}`}
                data-testid="interview-instructions-ack"
              >
                <Checkbox checked={instructionsAck} onCheckedChange={(v) => setInstructionsAck(!!v)} className="mt-0.5" />
                <span className="text-sm">
                  I have read and understood the above, including the proctoring policy and the 2-warning termination rule.
                  I'm in a quiet, uninterrupted environment and ready to begin.
                </span>
              </label>

              <Button size="lg" className="w-full" disabled={!instructionsAck} onClick={() => setConsentOpen(true)} data-testid="interview-open-consent-btn">
                Continue to start interview
              </Button>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
      )}

      {grants !== null && (
        <div className="mt-8 flex items-center justify-between">
          <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0} data-testid="interview-wizard-back-btn">
            <ArrowLeft className="h-4 w-4 mr-2" /> Back
          </Button>
          {step < steps.length - 1 && (
            <Button onClick={() => setStep((s) => Math.min(steps.length - 1, s + 1))} disabled={!canProceed()} data-testid="interview-wizard-next-btn">
              Next <ArrowRight className="h-4 w-4 ml-2" />
            </Button>
          )}
        </div>
      )}

      <AlertDialog open={consentOpen} onOpenChange={setConsentOpen}>
        <AlertDialogContent data-testid="interview-consent-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Enter fullscreen and begin?</AlertDialogTitle>
            <AlertDialogDescription>
              This locks the session into fullscreen and starts live proctoring right away — the interviewer will
              greet you within a few seconds. Make sure you're ready in a quiet space before confirming.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="interview-consent-cancel-btn">Not yet</AlertDialogCancel>
            <AlertDialogAction onClick={confirmAndStart} disabled={creating} data-testid="interview-consent-confirm-btn">
              {creating ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null} I agree — start interview
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
