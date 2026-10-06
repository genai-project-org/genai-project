import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { animate, motion, useMotionValue } from 'framer-motion';
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer,
} from 'recharts';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Loader2, Download, Briefcase, ThumbsUp, ThumbsDown, ShieldCheck, RefreshCw } from 'lucide-react';
import { detailToString, downloadBlob, DIMENSION_ORDER, DIMENSION_LABEL } from './interviewUtils';

const POLL_MS = 3000;
const MAX_POLL_ATTEMPTS = 100; // ~5 minutes — an abandoned session's report never generates, so this caps the wait

export default function InterviewReport() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [status, setStatus] = useState('pending'); // 'pending' | 'ready' | 'no_data' | 'stalled' | 'error'
  const [downloading, setDownloading] = useState(false);
  const attemptsRef = useRef(0);

  const fetchReport = async () => {
    try {
      const { data } = await api.get(`/interview/sessions/${sessionId}/report`);
      if (data.status === 'ready') {
        setReport(data);
        setStatus('ready');
        return true;
      }
      if (data.status === 'no_data' || data.status === 'failed') {
        setReport(data);
        setStatus(data.status);
        return true;
      }
      return false;
    } catch (e) {
      setStatus('error');
      toast.error(detailToString(e, 'Failed to load report'));
      return true; // stop polling on a hard error (e.g. 404 — not this user's session)
    }
  };

  useEffect(() => {
    let cancelled = false;
    let timeoutId;

    const loop = async () => {
      if (cancelled) return;
      attemptsRef.current += 1;
      const done = await fetchReport();
      if (cancelled || done) return;
      if (attemptsRef.current >= MAX_POLL_ATTEMPTS) {
        setStatus('stalled');
        return;
      }
      timeoutId = setTimeout(loop, POLL_MS);
    };
    loop();

    return () => { cancelled = true; if (timeoutId) clearTimeout(timeoutId); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const retryPolling = () => {
    attemptsRef.current = 0;
    setStatus('pending');
  };

  const downloadPdf = async () => {
    setDownloading(true);
    try {
      await downloadBlob(`/interview/sessions/${sessionId}/report/pdf`, `mock-interview-report-${sessionId.slice(0, 8)}.pdf`);
    } catch (e) {
      toast.error(detailToString(e, 'Download failed'));
    } finally {
      setDownloading(false);
    }
  };

  if (status === 'pending') {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center gap-4 text-center p-6" data-testid="interview-report-pending">
        <Loader2 className="h-10 w-10 animate-spin text-primary" />
        <div>
          <h2 className="font-display text-xl font-medium">Generating your report…</h2>
          <p className="text-sm text-muted-foreground mt-1">Scoring your interview and writing feedback — this takes a few moments.</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => navigate('/interview')} data-testid="interview-report-back-btn">Back to Mock Interviews</Button>
      </div>
    );
  }

  if (status === 'no_data') {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center gap-4 text-center p-6" data-testid="interview-report-no-data">
        <h2 className="font-display text-xl font-medium">No analysis available</h2>
        <p className="text-sm text-muted-foreground max-w-sm">
          This session ended without a single recorded answer, so there's nothing to score — usually a mic/camera
          permission issue or a dropped connection, not a reflection of your performance. This attempt wasn't evaluated.
        </p>
        <div className="flex gap-2">
          <Button onClick={() => navigate('/interview/new')} data-testid="interview-report-try-again-btn">Start a new interview</Button>
          <Button variant="outline" onClick={() => navigate('/interview')} data-testid="interview-report-back-btn">Back to Mock Interviews</Button>
        </div>
      </div>
    );
  }

  if (status === 'failed') {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center gap-4 text-center p-6" data-testid="interview-report-failed">
        <h2 className="font-display text-xl font-medium">Couldn't generate this report</h2>
        <p className="text-sm text-muted-foreground max-w-sm">Something went wrong while scoring this session. Your transcript is safe — try again shortly.</p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={retryPolling}>Check again</Button>
          <Button variant="outline" onClick={() => navigate('/interview')} data-testid="interview-report-back-btn">Back to Mock Interviews</Button>
        </div>
      </div>
    );
  }

  if (status === 'stalled' || status === 'error') {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center gap-4 text-center p-6" data-testid="interview-report-stalled">
        <h2 className="font-display text-xl font-medium">
          {status === 'error' ? "This report couldn't be loaded" : 'Still working on it'}
        </h2>
        <p className="text-sm text-muted-foreground max-w-sm">
          {status === 'error'
            ? "We couldn't find a report for this session."
            : "This is taking longer than usual — the session may not have generated a report (e.g. it was abandoned before any content). You can check back later."}
        </p>
        <div className="flex gap-2">
          {status === 'stalled' && (
            <Button variant="outline" onClick={retryPolling} data-testid="interview-report-retry-btn">
              <RefreshCw className="h-4 w-4 mr-2" /> Check again
            </Button>
          )}
          <Button onClick={() => navigate('/interview')}>Back to Mock Interviews</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6" data-testid="interview-report-page">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="mb-8">
        <h1 className="font-display text-3xl font-semibold tracking-tight">Your interview report</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {report.proctoring_summary?.violation_count > 0
            ? `${report.proctoring_summary.violation_count} proctoring flag(s) during this session.`
            : 'No proctoring flags during this session.'}
        </p>
      </motion.div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.05 }}
          className="rounded-2xl border border-primary/30 bg-primary/5 p-8 flex flex-col items-center justify-center"
          data-testid="interview-overall-score"
        >
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Overall score</div>
          <ScoreCountUp value={report.overall_score} />
          <div className="text-sm text-muted-foreground mt-1">/ 100</div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, delay: 0.15 }}
          className="rounded-2xl border border-border bg-card p-4"
        >
          <ResponsiveContainer width="100%" height={220}>
            <RadarChart data={DIMENSION_ORDER.map((d) => ({ dimension: DIMENSION_LABEL[d], score: report.dimension_scores?.[d] ?? 0 }))}>
              <PolarGrid stroke="hsl(var(--border))" />
              <PolarAngleAxis dataKey="dimension" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }} />
              <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
              <Radar dataKey="score" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.35} />
            </RadarChart>
          </ResponsiveContainer>
        </motion.div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.2 }}
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5" data-testid="interview-strengths"
        >
          <div className="flex items-center gap-1.5 font-medium text-emerald-600 dark:text-emerald-400 mb-2">
            <ThumbsUp className="h-4 w-4" /> Strengths
          </div>
          <ul className="space-y-1.5 text-sm">
            {(report.strengths || []).map((s, i) => <li key={i}>&middot; {s}</li>)}
            {(!report.strengths || report.strengths.length === 0) && <li className="text-muted-foreground">No strengths recorded.</li>}
          </ul>
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.25 }}
          className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-5" data-testid="interview-weaknesses"
        >
          <div className="flex items-center gap-1.5 font-medium text-amber-600 dark:text-amber-400 mb-2">
            <ThumbsDown className="h-4 w-4" /> Areas to improve
          </div>
          <ul className="space-y-1.5 text-sm">
            {(report.weaknesses || []).map((s, i) => <li key={i}>&middot; {s}</li>)}
            {(!report.weaknesses || report.weaknesses.length === 0) && <li className="text-muted-foreground">No gaps recorded.</li>}
          </ul>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.3 }}
        className="rounded-lg border border-border bg-card p-6 prose-chat mb-8" data-testid="interview-report-markdown"
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.report_markdown || ''}</ReactMarkdown>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.35 }}
        className="flex flex-wrap items-center gap-3"
      >
        <Button onClick={downloadPdf} disabled={downloading} data-testid="interview-report-download-btn">
          {downloading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Download className="h-4 w-4 mr-2" />} Download PDF
        </Button>
        <Button variant="outline" onClick={() => navigate('/career')} data-testid="interview-report-career-link">
          <Briefcase className="h-4 w-4 mr-2" /> View Career Intelligence
        </Button>
        <Button variant="ghost" onClick={() => navigate('/interview')}>
          Back to Mock Interviews
        </Button>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5" /> Proctoring integrity {Math.round(report.dimension_scores?.proctoring_integrity ?? 100)}/100
        </span>
      </motion.div>
    </div>
  );
}

function ScoreCountUp({ value }) {
  const mv = useMotionValue(0);
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const controls = animate(mv, value || 0, {
      duration: 1.4,
      ease: 'easeOut',
      onUpdate: (v) => setDisplay(Math.round(v)),
    });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return <div className="font-display text-6xl font-semibold tabular-nums" data-testid="interview-score-countup">{display}</div>;
}
