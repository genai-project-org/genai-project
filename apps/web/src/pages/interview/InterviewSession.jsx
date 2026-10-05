import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import { AnimatePresence, motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle,
  AlertDialogDescription, AlertDialogFooter, AlertDialogAction, AlertDialogCancel,
} from '@/components/ui/alert-dialog';
import {
  Mic, Square, Send, Keyboard, LogOut, Loader2, AlertTriangle, ShieldOff, PartyPopper,
} from 'lucide-react';
import AvatarStage from './AvatarStage';
import useProctoring from './useProctoring';
import { detailToString, fmtClock, TOPIC_META, VIOLATION_LABEL, MONACO_LANGUAGE, LANGUAGE_LABEL } from './interviewUtils';

const STATUS_POLL_MS = 4000;

export default function InterviewSession() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const [loading, setLoading] = useState(true);
  const [openingLoading, setOpeningLoading] = useState(true); // waiting on the interviewer's auto-generated opening greeting
  const [topic, setTopic] = useState(null);
  const [round, setRound] = useState('technical');
  const [sessionStatus, setSessionStatus] = useState(null);
  const [secondsLeft, setSecondsLeft] = useState(null);
  const [warningCount, setWarningCount] = useState(0);
  const [interviewer, setInterviewer] = useState(null); // {id, name} — assigned server-side, fixed for the whole session

  const [transcript, setTranscript] = useState([]); // [{speaker:'interviewer'|'candidate', text}]
  const [avatarState, setAvatarState] = useState('idle');
  const [amplitude, setAmplitude] = useState(0);
  const [busy, setBusy] = useState(false); // a turn is in flight (STT/LLM/TTS)
  const [busyLabel, setBusyLabel] = useState('');

  const [typedText, setTypedText] = useState('');
  const [showTypeInstead, setShowTypeInstead] = useState(false);
  const [recording, setRecording] = useState(false);
  const [code, setCode] = useState('// Talk through your approach, then write code here.\n');
  // Not just the initial setup pick — the interviewer can hand out
  // boilerplate in a different language per problem (e.g. no language
  // preference was set at setup), so this is kept in sync from
  // `code_boilerplate.language` wherever that arrives (see
  // beginInterviewOpening/submitTurn below) rather than frozen at mount.
  const [language, setLanguage] = useState(location.state?.language || 'python');

  const [ackRequired, setAckRequired] = useState(null); // violation label string while blocking
  const [borderPulse, setBorderPulse] = useState(false);
  const [roundTransition, setRoundTransition] = useState(false);
  const [completedOverlay, setCompletedOverlay] = useState(false);
  const [terminatedOverlay, setTerminatedOverlay] = useState(null); // reason string

  // The stream is ALSO kept in state (not just the ref below) so that
  // useProctoring — which depends on it in an effect dependency array —
  // reliably re-runs once getUserMedia resolves, rather than relying on an
  // incidental re-render ordering to have already populated the ref by the
  // time `enabled` flips true.
  const [stream, setStream] = useState(null);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const recordedChunksRef = useRef([]);
  const audioElRef = useRef(null);
  const ampRafRef = useRef(null);
  const prevRoundRef = useRef(null);
  const stoppedAllRef = useRef(false);
  const transcriptEndRef = useRef(null);

  const isDsa = topic === 'dsa';

  // ---- Initial load + camera/mic acquisition (ONE getUserMedia call, shared
  // by the self-camera PIP and the proctoring hook's face detection). -------
  useEffect(() => {
    let cancelled = false;
    // Reset here, not just at useRef() init — React 18 StrictMode
    // (src/index.jsx wraps the app in <React.StrictMode>) double-invokes
    // effects in development: mount -> cleanup -> mount again. The cleanup
    // below calls stopEverything(), which sets stoppedAllRef.current = true;
    // without this reset, that stays permanently stuck true after the very
    // FIRST load, silently making every submitTurn() call a no-op for the
    // rest of the session's lifetime (no error, no network request — the
    // interviewer simply never responds to anything, ever). Mirrors the
    // same reset useProctoring.js already does for its own stoppedRef.
    stoppedAllRef.current = false;
    (async () => {
      try {
        const { data } = await api.get(`/interview/sessions/${sessionId}/status`);
        if (cancelled) return;
        if (!['created', 'technical_in_progress', 'behavioral_in_progress'].includes(data.session_status)) {
          navigate(`/interview/${sessionId}/report`, { replace: true });
          return;
        }
        setTopic((prev) => prev); // topic isn't in /status; fetched from history fallback below
        setRound(data.round);
        setSessionStatus(data.session_status);
        setSecondsLeft(Math.round((data.minutes_remaining || 0) * 60));
        setWarningCount(data.warning_count || 0);
        if (data.interviewer) setInterviewer(data.interviewer);
        prevRoundRef.current = data.round;
      } catch (e) {
        toast.error(detailToString(e, 'Could not load this interview session'));
        navigate('/interview');
        return;
      }

      // Best-effort: pull the topic label from session history (status
      // endpoint doesn't return it, and we'd rather not add a backend call).
      try {
        const { data: hist } = await api.get('/interview/sessions?limit=20');
        const found = (hist.items || []).find((s) => s.id === sessionId);
        if (found && !cancelled) setTopic(found.topic);
      } catch { /* purely cosmetic — ignore */ }

      try {
        const mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        if (cancelled) { mediaStream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = mediaStream;
        setStream(mediaStream);
        // NOT `if (videoRef.current) videoRef.current.srcObject = ...` here —
        // the <video> element doesn't exist yet at this point (the component
        // is still showing the loading spinner return branch, gated on
        // `loading`), so that assignment used to silently land on a null ref
        // and never get retried once the real element mounted a moment
        // later, leaving the self-camera preview permanently blank. The
        // effect below (watching `stream`) re-attaches it once the <video>
        // element actually exists.
      } catch (e) {
        toast.error('Camera/microphone access is required for a proctored interview.');
      }

      if (!cancelled) {
        setLoading(false);
        beginInterviewOpening(); // fire-and-forget — the session shell renders immediately, opening arrives a few seconds later
      }
    })();

    return () => {
      cancelled = true;
      stopEverything();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const stopEverything = () => {
    stoppedAllRef.current = true;
    if (ampRafRef.current) cancelAnimationFrame(ampRafRef.current);
    if (streamRef.current) { streamRef.current.getTracks().forEach((t) => t.stop()); streamRef.current = null; setStream(null); }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      try { mediaRecorderRef.current.stop(); } catch { /* noop */ }
    }
  };

  // Attach the camera stream to the self-preview <video> once BOTH exist —
  // `stream` (state, so this re-runs when it arrives) and the element itself
  // (which only mounts once `loading` flips false). Either one arriving
  // after the other is fine; this covers both orders.
  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream, loading]);

  // ---- Status polling (source of truth for the timer + round) -------------
  useEffect(() => {
    if (loading || stoppedAllRef.current) return undefined;
    const poll = async () => {
      if (ackRequired || stoppedAllRef.current) return; // pause while a blocking warning is unacknowledged
      try {
        const { data } = await api.get(`/interview/sessions/${sessionId}/status`);
        setSecondsLeft(Math.round((data.minutes_remaining || 0) * 60));
        setWarningCount(data.warning_count || 0);
        if (data.round !== prevRoundRef.current) {
          prevRoundRef.current = data.round;
          setRound(data.round);
          if (data.round === 'behavioral') {
            setRoundTransition(true);
            setTimeout(() => setRoundTransition(false), 3600);
          }
        }
        if (data.session_status !== sessionStatus) {
          setSessionStatus(data.session_status);
          if (data.session_status === 'terminated_violations') {
            stopEverything();
            setTerminatedOverlay('Proctoring violation limit reached.');
          } else if (['completed', 'terminated_error', 'abandoned', 'expired'].includes(data.session_status)) {
            stopEverything();
            setCompletedOverlay(true);
            setTimeout(() => navigate(`/interview/${sessionId}/report`), 3500);
          }
        }
      } catch { /* transient network hiccup — next poll will retry */ }
    };
    const id = setInterval(poll, STATUS_POLL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, sessionId, ackRequired, sessionStatus]);

  // ---- Local 1s countdown tick, resynced by the poll above -----------------
  // The server clock only STARTS on the candidate's first submitted turn
  // (see interview_service.handle_turn) — while status is still "created",
  // /status returns a static default every time, not a live countdown. Tick
  // locally only once the round has actually started, so the display can't
  // count down a clock the server hasn't started yet and then "snap back"
  // to full duration on the next resync.
  const timerStarted = sessionStatus != null && sessionStatus !== 'created';
  useEffect(() => {
    if (loading || ackRequired || stoppedAllRef.current || !timerStarted) return undefined;
    const id = setInterval(() => {
      setSecondsLeft((s) => (s == null ? s : Math.max(0, s - 1)));
    }, 1000);
    return () => clearInterval(id);
  }, [loading, ackRequired, timerStarted]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  // ---- Proctoring ------------------------------------------------------------
  // Deliberately excludes `ackRequired`: while the blocking 2nd-warning
  // dialog is open, the candidate's focus naturally shifts to it (and the
  // round clock itself is paused server-side — see acknowledge_warning), so
  // detectors must stop entirely rather than flag the candidate for reading
  // a dialog they were required to read.
  const activeForProctoring = !loading && !terminatedOverlay && !completedOverlay && !ackRequired
    && ['created', 'technical_in_progress', 'behavioral_in_progress'].includes(sessionStatus);

  const handleProctoringResult = useCallback((data) => {
    setWarningCount(data.warning_count);
    setBorderPulse(true);
    setTimeout(() => setBorderPulse(false), 1200);
    if (data.terminated) {
      setAvatarState('warning');
      setTerminatedOverlay(`Proctoring violation: ${VIOLATION_LABEL[data.type] || data.type}.`);
      return;
    }
    if (data.warning_count >= 2) {
      setAckRequired(VIOLATION_LABEL[data.type] || data.type);
      setAvatarState('warning');
    } else {
      toast.warning(`Warning ${data.warning_count}/2: ${VIOLATION_LABEL[data.type] || data.type}`);
      setAvatarState('warning');
      setTimeout(() => setAvatarState('idle'), 2500);
    }
  }, []);

  const proctoring = useProctoring({
    sessionId,
    stream,
    videoEl: videoRef,
    enabled: activeForProctoring,
    onResult: handleProctoringResult,
    onError: () => {}, // model/detection failures degrade silently, per design
  });

  // ---- Playing the interviewer's TTS audio + driving avatar amplitude ------
  // Deliberately NOT routed through the Web Audio API (AudioContext +
  // MediaElementSource) — a freshly-created AudioContext starts *suspended*
  // in Chrome, and resume() called from inside an async response handler
  // (rather than directly inside a click handler) can silently fail to
  // actually resume it, muting all audio while .play() still "succeeds" with
  // no error. Playing the <audio> element directly is the most reliable path
  // to actual sound; the avatar's "talking" motion falls back to a smooth
  // synthetic wobble instead of true frequency analysis — an explicitly
  // accepted approximation (this app was never doing true viseme lip-sync
  // anyway), traded for audio that unconditionally plays.
  const playInterviewerAudio = (base64Wav) => {
    if (!base64Wav || !audioElRef.current) { setAvatarState('idle'); return; }
    const audioEl = audioElRef.current;
    audioEl.src = `data:audio/wav;base64,${base64Wav}`;
    audioEl.currentTime = 0;
    setAvatarState('talking');

    const tick = () => {
      const t = audioEl.currentTime || 0;
      const synthetic = 0.35 + 0.35 * Math.abs(Math.sin(t * 9)) + 0.15 * Math.abs(Math.sin(t * 23));
      setAmplitude(Math.min(1, synthetic));
      if (!audioEl.paused && !audioEl.ended) ampRafRef.current = requestAnimationFrame(tick);
    };

    audioEl.play().then(tick).catch((err) => {
      console.warn('Interviewer audio playback failed:', err);
      toast.error('Could not play the interviewer’s voice — you can still read their reply below.');
      setAvatarState('idle');
      setAmplitude(0);
    });

    audioEl.onended = () => {
      if (ampRafRef.current) cancelAnimationFrame(ampRafRef.current);
      setAvatarState('nodding');
      setAmplitude(0);
      setTimeout(() => setAvatarState('idle'), 1200);
    };
  };

  // ---- Auto-start: the interviewer greets you and asks the first question,
  // exactly like a real interview — the candidate never has to speak first.
  // Fired once on mount (see the initial-load effect above); idempotent
  // server-side, so a page refresh mid-interview just replays the existing
  // opening rather than generating (or paying for) a new one.
  const beginInterviewOpening = async () => {
    try {
      const { data } = await api.post(`/interview/sessions/${sessionId}/start`);
      setTranscript((t) => (data.interviewer_text ? [...t, { speaker: 'interviewer', text: data.interviewer_text }] : t));
      setSessionStatus(data.session_status);
      setRound(data.round);
      prevRoundRef.current = data.round;
      setSecondsLeft(Math.round((data.minutes_remaining || 0) * 60));
      setWarningCount(data.warning_count || 0);
      if (data.interviewer) setInterviewer(data.interviewer);
      if (data.code_boilerplate?.code) setCode(data.code_boilerplate.code);
      if (data.code_boilerplate?.language && MONACO_LANGUAGE[data.code_boilerplate.language]) {
        setLanguage(data.code_boilerplate.language);
      }
      if (data.interviewer_audio_base64) playInterviewerAudio(data.interviewer_audio_base64);
    } catch (e) {
      toast.error(detailToString(e, 'Could not start the interview — try refreshing the page.'));
    } finally {
      setOpeningLoading(false);
    }
  };

  // ---- Submitting a turn -----------------------------------------------------
  const submitTurn = async ({ modality, text = '', audioBlob = null }) => {
    if (busy || stoppedAllRef.current) return;
    setBusy(true);
    setBusyLabel(modality === 'voice' ? 'Transcribing…' : 'Thinking…');
    setAvatarState('thinking');
    try {
      const form = new FormData();
      form.append('modality', modality);
      form.append('text', text);
      if (audioBlob) form.append('audio', audioBlob, 'answer.webm');
      const { data } = await api.post(`/interview/sessions/${sessionId}/turn`, form);

      setTranscript((t) => [
        ...t,
        ...(data.transcript ? [{ speaker: 'candidate', text: modality === 'code' ? `\`\`\`${language}\n${data.transcript}\n\`\`\`` : data.transcript }] : []),
        ...(data.interviewer_text ? [{ speaker: 'interviewer', text: data.interviewer_text }] : []),
      ]);
      setWarningCount(data.warning_count || 0);
      setRound(data.round);
      prevRoundRef.current = data.round;
      setSecondsLeft(Math.round((data.minutes_remaining || 0) * 60));
      if (data.session_status !== sessionStatus) setSessionStatus(data.session_status);
      if (data.code_boilerplate?.code) setCode(data.code_boilerplate.code);
      if (data.code_boilerplate?.language && MONACO_LANGUAGE[data.code_boilerplate.language]) {
        setLanguage(data.code_boilerplate.language);
      }

      setBusyLabel('');
      playInterviewerAudio(data.interviewer_audio_base64);
    } catch (e) {
      toast.error(detailToString(e, 'That turn failed — try again'));
      setAvatarState('idle');
    } finally {
      setBusy(false);
      setBusyLabel('');
    }
  };

  const sendTyped = () => {
    if (!typedText.trim() || busy) return;
    submitTurn({ modality: 'text', text: typedText.trim() });
    setTypedText('');
  };

  const submitCode = () => {
    if (busy) return;
    submitTurn({ modality: 'code', text: code });
  };

  // ---- Mid-interview coding-language switch (DSA technical round only) -----
  // Updates both sides at once: the candidate's own editor syntax AND what
  // the interviewer writes boilerplate/discusses code in from here on.
  const [changingLanguage, setChangingLanguage] = useState(false);
  const changeLanguage = async (newLanguage) => {
    if (newLanguage === language || busy || changingLanguage || openingLoading || !!ackRequired) return;
    setChangingLanguage(true);
    setBusyLabel('Switching language…');
    setAvatarState('thinking');
    try {
      const { data } = await api.post(`/interview/sessions/${sessionId}/language`, { language: newLanguage });
      setLanguage(newLanguage);
      if (data.interviewer_text) {
        setTranscript((t) => [...t, { speaker: 'interviewer', text: data.interviewer_text }]);
      }
      if (data.code_boilerplate?.code) setCode(data.code_boilerplate.code);
      if (data.interviewer_audio_base64) playInterviewerAudio(data.interviewer_audio_base64);
      else setAvatarState('idle');
    } catch (e) {
      toast.error(detailToString(e, 'Could not switch language — try again.'));
      setAvatarState('idle');
    } finally {
      setChangingLanguage(false);
      setBusyLabel('');
    }
  };

  // ---- Push-to-talk voice recording ------------------------------------------
  const startRecording = () => {
    if (!streamRef.current || busy || recording) return;
    const audioTracks = streamRef.current.getAudioTracks();
    if (!audioTracks.length) return toast.error('No microphone available.');
    try {
      const audioOnlyStream = new MediaStream(audioTracks);
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
      const recorder = new MediaRecorder(audioOnlyStream, { mimeType });
      recordedChunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunksRef.current.push(e.data); };
      recorder.onstop = () => {
        const blob = new Blob(recordedChunksRef.current, { type: mimeType });
        submitTurn({ modality: 'voice', audioBlob: blob });
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      setRecording(true);
      setAvatarState('listening');
    } catch {
      toast.error('Could not start recording.');
    }
  };

  const stopRecording = () => {
    if (!recording) return;
    setRecording(false);
    try { mediaRecorderRef.current?.stop(); } catch { /* noop */ }
  };

  // Deliberately an in-app AlertDialog, never window.confirm()/alert() —
  // browsers auto-exit fullscreen the instant a NATIVE dialog opens
  // (regardless of what the user clicks), which useProctoring's
  // fullscreenchange listener would otherwise report as a violation on
  // every single End click, and which briefly gives the candidate a real
  // window to alt-tab/switch apps before dismissing it. An in-page dialog
  // does neither: fullscreen stays intact, and canceling never touches
  // proctoring at all.
  const [endDialogOpen, setEndDialogOpen] = useState(false);
  const [ending, setEnding] = useState(false);

  const confirmEndInterview = async () => {
    setEnding(true);
    // Stop the proctoring hook FIRST, before we deliberately exit fullscreen
    // ourselves — otherwise our own intentional exitFullscreen() call below
    // would immediately be reported as a violation by the same listener.
    proctoring.stop();
    stopEverything();
    if (document.fullscreenElement) {
      try { await document.exitFullscreen(); } catch { /* noop */ }
    }
    try {
      await api.post(`/interview/sessions/${sessionId}/end`);
    } catch { /* best-effort */ }
    navigate(`/interview/${sessionId}/report`);
  };

  const [acking, setAcking] = useState(false);
  const ackWarning = async () => {
    setAcking(true);
    try {
      const { data } = await api.post(`/interview/sessions/${sessionId}/acknowledge`);
      setSecondsLeft(Math.round((data.minutes_remaining || 0) * 60));
      if (data.round !== prevRoundRef.current) { prevRoundRef.current = data.round; setRound(data.round); }
      setSessionStatus(data.session_status);
    } catch (e) {
      toast.error(detailToString(e, 'Could not resume — try refreshing the page.'));
    } finally {
      setAcking(false);
      setAckRequired(null);
    }
  };

  const topicMeta = TOPIC_META[topic] || { label: topic || '' };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (terminatedOverlay) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-6" data-testid="interview-terminated-screen">
        <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="max-w-md text-center space-y-4">
          <ShieldOff className="h-14 w-14 text-destructive mx-auto" />
          <h1 className="font-display text-2xl font-semibold">Interview ended — proctoring violation</h1>
          <p className="text-sm text-muted-foreground">{terminatedOverlay}</p>
          <p className="text-xs text-muted-foreground">Your progress so far has been saved and a partial report will be generated.</p>
          <Button onClick={() => navigate(`/interview/${sessionId}/report`)} data-testid="interview-terminated-report-btn">View report</Button>
        </motion.div>
      </div>
    );
  }

  if (completedOverlay) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-6" data-testid="interview-completed-screen">
        <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="max-w-md text-center space-y-4">
          <PartyPopper className="h-14 w-14 text-primary mx-auto" />
          <h1 className="font-display text-2xl font-semibold">Interview complete!</h1>
          <p className="text-sm text-muted-foreground">Generating your report — this takes a few moments.</p>
          <Loader2 className="h-5 w-5 animate-spin mx-auto text-primary" />
        </motion.div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}
      className="min-h-screen bg-background flex flex-col"
      data-testid="interview-live-page"
    >
      <audio ref={audioElRef} className="hidden" />

      {/* Red pulse border on a proctoring warning */}
      <AnimatePresence>
        {borderPulse && (
          <motion.div
            className="fixed inset-0 pointer-events-none z-40 border-4 border-rose-500"
            initial={{ opacity: 0 }} animate={{ opacity: [0, 0.8, 0] }} exit={{ opacity: 0 }} transition={{ duration: 1.2 }}
          />
        )}
      </AnimatePresence>

      {/* Top bar */}
      <div className="flex items-center justify-between gap-3 px-5 h-14 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Badge variant="outline">{topicMeta.label}</Badge>
          <Badge variant={round === 'technical' ? 'default' : 'secondary'}>
            {round === 'technical' ? 'Technical round' : 'Behavioral round'}
          </Badge>
        </div>
        <div className="text-center" data-testid="interview-timer">
          {timerStarted ? (
            <div className="font-display text-xl font-semibold tabular-nums">{fmtClock((secondsLeft ?? 0) / 60)}</div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Connecting to your interviewer…
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="interview-warning-indicator">
            <AlertTriangle className={`h-3.5 w-3.5 ${warningCount > 0 ? 'text-amber-500' : ''}`} /> {warningCount}/2 warnings
          </span>
          <Button variant="outline" size="sm" onClick={() => setEndDialogOpen(true)} data-testid="interview-end-btn">
            <LogOut className="h-3.5 w-3.5 mr-1.5" /> End
          </Button>
        </div>
      </div>

      {/* Round transition interstitial */}
      <AnimatePresence>
        {roundTransition && (
          <motion.div
            className="fixed inset-0 z-50 bg-background/95 backdrop-blur flex items-center justify-center"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          >
            <motion.div
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ staggerChildren: 0.15 }}
              className="text-center space-y-3"
            >
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                <Badge className="mb-2">Technical round complete</Badge>
              </motion.div>
              <motion.h2 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }} className="font-display text-3xl font-semibold">
                Behavioral round starting…
              </motion.h2>
              <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="text-sm text-muted-foreground">
                Tell your story
              </motion.p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main two-zone layout */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-0 min-h-0">
        {/* Left: avatar + PIP + controls */}
        <div className="flex flex-col items-center justify-between p-6 border-r border-border min-h-0">
          <div />
          <AvatarStage state={avatarState} amplitude={amplitude} interviewer={interviewer} />

          <div className="w-full max-w-sm space-y-3">
            {busyLabel && (
              <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground" data-testid="interview-busy-label">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> {busyLabel}
              </div>
            )}
            <div className="flex items-center justify-center gap-3">
              <video ref={videoRef} autoPlay muted playsInline className="w-24 h-16 rounded-md object-cover -scale-x-100 border border-border bg-black" data-testid="interview-self-pip" />
              <Button
                size="lg"
                variant={recording ? 'destructive' : 'default'}
                className="rounded-full h-16 w-16 p-0"
                onClick={recording ? stopRecording : startRecording}
                disabled={busy || !!ackRequired}
                data-testid="interview-mic-btn"
                title={recording ? 'Click when you’re done answering' : 'Click to answer'}
              >
                {recording ? <Square className="h-6 w-6" /> : <Mic className="h-6 w-6" />}
              </Button>
            </div>
            <p className="text-center text-xs text-muted-foreground" data-testid="interview-mic-hint">
              {recording ? (
                <span className="flex items-center justify-center gap-1.5 text-destructive">
                  <span className="h-1.5 w-1.5 rounded-full bg-destructive animate-pulse" /> Recording — click when you're done answering
                </span>
              ) : 'Click the mic to answer'}
            </p>
            <button
              type="button"
              onClick={() => setShowTypeInstead((v) => !v)}
              className="w-full text-center text-xs text-muted-foreground hover:text-foreground flex items-center justify-center gap-1"
              data-testid="interview-type-instead-toggle"
            >
              <Keyboard className="h-3.5 w-3.5" /> Type instead
            </button>
            {showTypeInstead && (
              <div className="flex gap-2">
                <Input
                  value={typedText} onChange={(e) => setTypedText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') sendTyped(); }}
                  placeholder="Type your answer…" disabled={busy || !!ackRequired}
                  data-testid="interview-typed-input"
                />
                <Button size="icon" onClick={sendTyped} disabled={busy || !!ackRequired} data-testid="interview-typed-send-btn">
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Right: Monaco (DSA) or transcript panel */}
        <div className="flex flex-col min-h-0">
          {isDsa ? (
            <div className="flex flex-col h-full min-h-0">
              <div className="flex-1 overflow-y-auto p-4 space-y-3 max-h-56 border-b border-border" data-testid="interview-dsa-transcript">
                <TranscriptFeed transcript={transcript} endRef={transcriptEndRef} openingLoading={openingLoading} />
              </div>
              <div className="flex-1 min-h-0 flex flex-col">
                <div className="flex items-center justify-between px-3 py-2 border-b border-border gap-2">
                  <span className="text-xs text-muted-foreground shrink-0">Code editor</span>
                  <div className="flex items-center gap-2">
                    <Select value={language} onValueChange={changeLanguage} disabled={busy || changingLanguage || openingLoading || !!ackRequired}>
                      <SelectTrigger className="h-8 w-[130px] text-xs" data-testid="interview-language-switch">
                        {changingLanguage ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <SelectValue />}
                      </SelectTrigger>
                      <SelectContent>
                        {Object.keys(MONACO_LANGUAGE).map((v) => (
                          <SelectItem key={v} value={v}>{LANGUAGE_LABEL[v] || v}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button size="sm" onClick={submitCode} disabled={busy || !!ackRequired} data-testid="interview-submit-code-btn">
                      {busy ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : null} Discuss this code
                    </Button>
                  </div>
                </div>
                <Editor
                  height="100%"
                  language={MONACO_LANGUAGE[language]}
                  theme="vs-dark"
                  value={code}
                  onChange={(v) => setCode(v ?? '')}
                  options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, automaticLayout: true }}
                  data-testid="interview-editor"
                />
              </div>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto p-5 space-y-4" data-testid="interview-transcript-panel">
              <TranscriptFeed transcript={transcript} endRef={transcriptEndRef} openingLoading={openingLoading} />
            </div>
          )}
        </div>
      </div>

      {/* 2nd-warning blocking acknowledgment */}
      <AlertDialog open={!!ackRequired}>
        <AlertDialogContent data-testid="interview-ack-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-amber-500" /> Second proctoring warning</AlertDialogTitle>
            <AlertDialogDescription>
              {ackRequired}. This is your final warning — one more confirmed violation will end the interview immediately.
              Your timer is paused until you acknowledge.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction onClick={ackWarning} disabled={acking} data-testid="interview-ack-confirm-btn">
              {acking ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null} I understand — continue
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* End-interview confirmation — an in-page dialog on purpose, never
          window.confirm(): see confirmEndInterview's comment. */}
      <AlertDialog open={endDialogOpen} onOpenChange={(o) => !ending && setEndDialogOpen(o)}>
        <AlertDialogContent data-testid="interview-end-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>End this interview now?</AlertDialogTitle>
            <AlertDialogDescription>
              This can't be undone — your progress so far will be saved and a report generated from whatever was covered.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="interview-end-cancel-btn" disabled={ending}>Keep going</AlertDialogCancel>
            <AlertDialogAction onClick={confirmEndInterview} disabled={ending} data-testid="interview-end-confirm-btn">
              {ending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null} End interview
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </motion.div>
  );
}

function TranscriptFeed({ transcript, endRef, openingLoading }) {
  if (transcript.length === 0) {
    return (
      <p className="text-sm text-muted-foreground text-center py-8 flex items-center justify-center gap-2">
        {openingLoading ? (<><Loader2 className="h-3.5 w-3.5 animate-spin" /> The interviewer is joining…</>) : 'Click the mic to reply.'}
      </p>
    );
  }
  return (
    <>
      {transcript.map((t, i) => (
        <div key={i} className={`flex ${t.speaker === 'candidate' ? 'justify-end' : 'justify-start'}`}>
          <div
            className={`max-w-[85%] rounded-lg px-3 py-2 text-sm prose-chat ${t.speaker === 'candidate' ? 'bg-primary/10 border border-primary/20' : 'bg-muted/50 border border-border'}`}
            data-testid={`interview-turn-${t.speaker}`}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.text}</ReactMarkdown>
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </>
  );
}
