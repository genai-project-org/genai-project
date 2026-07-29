import { useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import api from '@/lib/api';
import { setWalletBalance } from '@/store/slices/uiSlice';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Loader2, Briefcase, MapPin, IndianRupee, ExternalLink, GraduationCap, Sparkles, FileText, Upload, X } from 'lucide-react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Tabs are path-driven (/career, /career/path, /career/resume) rather than local state so
// the sidebar can deep-link straight to Resume. Same shape as /builder + /builder/dynamic.
const TABS = ['jobs', 'path', 'resume'];

// FastAPI returns `detail` as an object for 402/429 (credit + window limits) and an array
// for 422. Passing either to toast.error unmounts the page, so flatten first.
function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

export default function Career() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const active = TABS.includes(tab) ? tab : 'jobs';

  return (
    <div className="max-w-6xl mx-auto p-6" data-testid="career-page">
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Briefcase className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Career Intelligence</h1>
            <p className="text-sm text-muted-foreground">India-focused job search, AI learning paths, and resume ATS scoring (cached to save credits).</p>
          </div>
        </div>
      </div>
      <Tabs value={active} onValueChange={(v) => navigate(v === 'jobs' ? '/career' : `/career/${v}`)}>
        <TabsList>
          <TabsTrigger value="jobs" data-testid="career-tab-jobs"><Briefcase className="h-4 w-4 mr-2" />Jobs</TabsTrigger>
          <TabsTrigger value="path" data-testid="career-tab-path"><GraduationCap className="h-4 w-4 mr-2" />Learning Path</TabsTrigger>
          <TabsTrigger value="resume" data-testid="career-tab-resume"><FileText className="h-4 w-4 mr-2" />Resume</TabsTrigger>
        </TabsList>
        <TabsContent value="jobs"><Jobs /></TabsContent>
        <TabsContent value="path"><LearningPath /></TabsContent>
        <TabsContent value="resume"><ResumeTab /></TabsContent>
      </Tabs>
    </div>
  );
}

function Jobs() {
  const [query, setQuery] = useState('python developer');
  const [location, setLocation] = useState('Bengaluru');
  const [items, setItems] = useState([]);
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(false);

  const search = async () => {
    if (!query.trim()) return toast.error('Enter a role or skill');
    setLoading(true);
    try {
      const { data } = await api.post('/career/jobs', { query, location, page: 1 });
      setItems(data.results || []); setSource(data.source || '');
    } catch (e) { toast.error(e.response?.data?.detail || 'Search failed'); }
    finally { setLoading(false); }
  };

  return (
    <div className="mt-6 space-y-4">
      <div className="flex flex-col sm:flex-row gap-2 rounded-lg border border-border bg-card p-3">
        <Input data-testid="career-jobs-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Role or skill (e.g. React developer)" className="flex-1" />
        <Input data-testid="career-jobs-location" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="City or state" className="sm:w-56" />
        <Button data-testid="career-jobs-search-btn" onClick={search} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Briefcase className="h-4 w-4 mr-2" />}
          Search
        </Button>
      </div>
      {source === 'mock' && (
        <div className="rounded-md bg-yellow-500/10 border border-yellow-500/30 text-yellow-700 dark:text-yellow-400 text-xs px-3 py-2">
          Showing sample listings. Configure ADZUNA_APP_ID / ADZUNA_APP_KEY in backend .env for live data.
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="career-jobs-results">
        {items.map((j) => (
          <a key={j.id} href={j.url} target="_blank" rel="noreferrer" className="block rounded-lg border border-border bg-card p-4 hover:border-primary/40 transition-colors">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-medium truncate">{j.title}</div>
                <div className="text-sm text-muted-foreground">{j.company}</div>
              </div>
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
            </div>
            <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
              {j.location && <span className="flex items-center gap-1"><MapPin className="h-3 w-3" />{j.location}</span>}
              {j.salary_min && <span className="flex items-center gap-1"><IndianRupee className="h-3 w-3" />{Math.round(j.salary_min / 100000)}–{Math.round((j.salary_max || j.salary_min) / 100000)} LPA</span>}
            </div>
            <p className="mt-3 text-xs text-muted-foreground line-clamp-3">{j.description}</p>
          </a>
        ))}
        {!loading && items.length === 0 && <div className="text-sm text-muted-foreground py-8 text-center col-span-full">Search to see jobs.</div>}
      </div>
    </div>
  );
}

function LearningPath() {
  const [role, setRole] = useState('');
  const [skills, setSkills] = useState('');
  const [result, setResult] = useState('');
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!role.trim()) return toast.error('Enter a target role');
    setLoading(true); setResult(''); setMeta(null);
    try {
      const skillsArr = skills.split(',').map(s => s.trim()).filter(Boolean);
      const { data } = await api.post('/career/learning-path', { role, skills: skillsArr });
      setResult(data.roadmap_markdown);
      setMeta({ cached: data.cached, credits: data.credits_used });
      toast.success('Ready');
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
    finally { setLoading(false); }
  };

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <Input data-testid="career-path-role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Target role (e.g. Backend Python Engineer)" />
        <Input data-testid="career-path-skills" value={skills} onChange={(e) => setSkills(e.target.value)} placeholder="Current skills (comma-separated)" />
        <div className="flex items-center justify-between">
          <div className="text-xs text-muted-foreground">Instant results (cached after first generation)</div>
          <Button data-testid="career-path-btn" onClick={run} disabled={loading || !role.trim()}>
            {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Sparkles className="h-4 w-4 mr-2" />}
            Generate Path
          </Button>
        </div>
      </div>
      {meta && (
        <div className="text-xs text-muted-foreground">
          Ready
        </div>
      )}
      {result && (
        <div className="rounded-lg border border-border bg-card p-6 prose-chat" data-testid="career-path-result">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{result}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

const MIN_RESUME_CHARS = 200;   // mirrors resume_service.MIN_RESUME_CHARS
const MAX_FILE_BYTES = 5 * 1024 * 1024;

// Bands for the shortlist estimate. Derived here rather than parsed out of the report so
// the number and its label can never disagree.
const band = (n) => (n == null ? '' : n >= 65 ? 'Strong' : n >= 35 ? 'Moderate' : 'Long shot');

function ResumeTab() {
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
  const dispatch = useDispatch();

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
      if (data.balance != null) dispatch(setWalletBalance(data.balance));
    } catch (e) {
      toast.error(detailToString(e, 'Resume analysis failed'));
    } finally { setLoading(false); }
  };

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="hidden"
            onChange={(e) => pickFile(e.target.files?.[0])}
            data-testid="career-resume-file-input"
          />
          <Button variant="outline" onClick={() => fileRef.current?.click()} data-testid="career-resume-pick-btn">
            <Upload className="h-4 w-4 mr-2" />
            {file ? 'Change file' : 'Upload resume'}
          </Button>
          {file ? (
            <span className="flex items-center gap-2 text-sm text-muted-foreground min-w-0">
              <FileText className="h-4 w-4 flex-shrink-0" />
              <span className="truncate">{file.name}</span>
              <button onClick={clearFile} className="hover:text-destructive flex-shrink-0" aria-label="Remove file" data-testid="career-resume-clear-btn">
                <X className="h-4 w-4" />
              </button>
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">PDF, DOCX or TXT · max 5MB</span>
          )}
        </div>

        {!file && (
          <Textarea
            data-testid="career-resume-text"
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            rows={6}
            placeholder={`…or paste your resume text here (at least ${MIN_RESUME_CHARS} characters)`}
            className="resize-none"
          />
        )}

        <Input data-testid="career-resume-role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Target role (optional, e.g. Backend Python Engineer)" />
        <Textarea
          data-testid="career-resume-jd"
          value={jd}
          onChange={(e) => setJd(e.target.value)}
          rows={4}
          placeholder="Paste the job description (optional — enables keyword matching)"
          className="resize-none"
        />

        <div className="flex items-center justify-between">
          <div className="text-xs text-muted-foreground">Your resume is analyzed in memory and never stored.</div>
          <Button data-testid="career-resume-btn" onClick={run} disabled={loading || !ready}>
            {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Sparkles className="h-4 w-4 mr-2" />}
            Analyze Resume
          </Button>
        </div>
      </div>

      {report && (
        <div className="rounded-lg border border-border bg-card p-6 space-y-4" data-testid="career-resume-result">
          <div className="flex flex-wrap items-stretch gap-3">
            <div className="rounded-xl bg-primary/10 border border-primary/20 px-5 py-3 min-w-[9rem]" data-testid="career-resume-score">
              <div className="text-xs text-muted-foreground">ATS Score</div>
              <div className="text-2xl font-semibold leading-tight">
                {scores.ats ?? '—'}<span className="text-sm text-muted-foreground font-normal"> / 100</span>
              </div>
            </div>
            <div className="rounded-xl bg-primary/10 border border-primary/20 px-5 py-3 min-w-[9rem]" data-testid="career-resume-shortlist">
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
                data-testid="career-resume-parsed-toggle"
              >
                {showParsed ? 'Hide' : 'Show'} the text the parser extracted ({parsed.length.toLocaleString()} chars)
              </button>
              {showParsed && (
                <pre className="mt-2 max-h-80 overflow-auto rounded-lg border border-border bg-muted/30 p-3 text-xs whitespace-pre-wrap font-mono" data-testid="career-resume-parsed">
                  {parsed}
                </pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
