import { useRef, useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Loader2, Sparkles, FileText, Upload, X } from 'lucide-react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const MIN_RESUME_CHARS = 200;   // mirrors resume_service.MIN_RESUME_CHARS
const MAX_FILE_BYTES = 5 * 1024 * 1024;

// Bands for the shortlist estimate. Derived here rather than parsed out of the report so
// the number and its label can never disagree.
const band = (n) => (n == null ? '' : n >= 65 ? 'Strong' : n >= 35 ? 'Moderate' : 'Long shot');

// FastAPI returns `detail` as an object for 402/429 (credit + window limits) and an array
// for 422. Passing either to toast.error unmounts the page, so flatten first.
function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

export default function Resume() {
  const [file, setFile] = useState(null);
  const [pasted, setPasted] = useState('');
  const [role, setRole] = useState('');
  const [jd, setJd] = useState('');
  const [report, setReport] = useState('');
  const [scores, setScores] = useState({});
  const [parsed, setParsed] = useState('');
  const [showParsed, setShowParsed] = useState(false);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const fileRef = useRef(null);

  const ready = !!file || pasted.trim().length >= MIN_RESUME_CHARS;

  const pickFile = (f) => {
    if (!f) return;
    if (f.size > MAX_FILE_BYTES) return toast.error('File too large. Max 5MB.');
    setFile(f);
    setPasted('');   // a file wins; keep one source of truth visible
  };

  const clearFile = () => {
    setFile(null);
    if (fileRef.current) fileRef.current.value = '';  // so re-picking the same file refires onChange
  };

  const run = async () => {
    if (!ready) return;
    setLoading(true); setReport(''); setScores({}); setParsed(''); setMeta(null);
    try {
      const form = new FormData();
      // Append only when a real file exists — an empty file input part arrives as an
      // UploadFile with filename="", which the backend would have to special-case.
      if (file) form.append('file', file);
      form.append('resume_text', file ? '' : pasted);
      form.append('job_description', jd);
      form.append('target_role', role);
      const { data } = await api.post('/resume/analyze', form);
      setReport(data.response);
      setScores({ ats: data.ats_score, shortlist: data.shortlist_chance });
      setParsed(data.resume_text || '');
      setMeta({ source: data.source, credits: data.credits_used });
      // wallet counter is updated by the response interceptor in lib/api.js
    } catch (e) {
      toast.error(detailToString(e, 'Resume analysis failed'));
    } finally { setLoading(false); }
  };

  return (
    <div className="max-w-6xl mx-auto p-6" data-testid="resume-page">
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
            <FileText className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Resume Intelligence</h1>
            <p className="text-sm text-muted-foreground">ATS scoring, keyword matching against a job description, and rewritten bullets.</p>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt,.md"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0])}
              data-testid="resume-file-input"
            />
            <Button variant="outline" onClick={() => fileRef.current?.click()} data-testid="resume-pick-btn">
              <Upload className="h-4 w-4 mr-2" />
              {file ? 'Change file' : 'Upload resume'}
            </Button>
            {file ? (
              <span className="flex items-center gap-2 text-sm text-muted-foreground min-w-0">
                <FileText className="h-4 w-4 flex-shrink-0" />
                <span className="truncate">{file.name}</span>
                <button onClick={clearFile} className="hover:text-destructive flex-shrink-0" aria-label="Remove file" data-testid="resume-clear-btn">
                  <X className="h-4 w-4" />
                </button>
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">PDF, DOCX or TXT · max 5MB</span>
            )}
          </div>

          {!file && (
            <Textarea
              data-testid="resume-text"
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              rows={6}
              placeholder={`…or paste your resume text here (at least ${MIN_RESUME_CHARS} characters)`}
              className="resize-none"
            />
          )}

          <Input data-testid="resume-role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Target role (optional, e.g. Backend Python Engineer)" />
          <Textarea
            data-testid="resume-jd"
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            rows={4}
            placeholder="Paste the job description (optional — enables keyword matching)"
            className="resize-none"
          />

          <div className="flex items-center justify-between">
            <div className="text-xs text-muted-foreground">Your resume is analyzed in memory and never stored.</div>
            <Button data-testid="resume-btn" onClick={run} disabled={loading || !ready}>
              {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Sparkles className="h-4 w-4 mr-2" />}
              Analyze Resume
            </Button>
          </div>
        </div>

        {report && (
          <div className="rounded-lg border border-border bg-card p-6 space-y-4" data-testid="resume-result">
            <div className="flex flex-wrap items-stretch gap-3">
              <div className="rounded-xl bg-primary/10 border border-primary/20 px-5 py-3 min-w-[9rem]" data-testid="resume-score">
                <div className="text-xs text-muted-foreground">ATS Score</div>
                <div className="text-2xl font-semibold leading-tight">
                  {scores.ats ?? '—'}<span className="text-sm text-muted-foreground font-normal"> / 100</span>
                </div>
              </div>
              <div className="rounded-xl bg-primary/10 border border-primary/20 px-5 py-3 min-w-[9rem]" data-testid="resume-shortlist">
                <div className="text-xs text-muted-foreground">Shortlist Chance</div>
                <div className="text-2xl font-semibold leading-tight">
                  {scores.shortlist != null ? `${scores.shortlist}%` : '—'}
                  {scores.shortlist != null && <span className="text-sm text-muted-foreground font-normal"> {band(scores.shortlist)}</span>}
                </div>
              </div>
              <div className="flex items-end text-sm text-muted-foreground">
                {meta?.source === 'kb' ? 'Served from cache — no credits used.' : `${meta?.credits ?? 0} credits used.`}
              </div>
            </div>

            <p className="text-[11px] text-muted-foreground italic border-t border-border/50 pt-2">
              Shortlist chance is an AI estimate from your resume and the job description alone — it
              can't see the other applicants, the hiring bar, or the recruiter. Treat it as a
              direction to push, not a prediction.
            </p>

            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
            </div>

            {parsed && (
              <div className="border-t border-border pt-3">
                <button
                  onClick={() => setShowParsed((v) => !v)}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                  data-testid="resume-parsed-toggle"
                >
                  {showParsed ? 'Hide' : 'Show'} the text the parser extracted ({parsed.length.toLocaleString()} chars)
                </button>
                {showParsed && (
                  <pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-border bg-muted/30 p-3 text-xs whitespace-pre-wrap font-mono" data-testid="resume-parsed">
                    {parsed}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
