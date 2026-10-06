import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Loader2, Play, Code2, CheckCircle2, XCircle, Coins, Database, ListChecks, PencilRuler } from 'lucide-react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from '@/components/ui/accordion';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Lightbulb, Lock, History, Youtube } from 'lucide-react';
import DesignDiagramCanvas, { exportDiagramForSubmit } from '@/components/practice/DesignDiagramCanvas';
import CalculationScratchpad from '@/components/practice/CalculationScratchpad';

// Rubric criteria tagged `applies_to: "diagram"|"calculation"` render a small
// badge so a candidate can see at a glance which part of their submission
// each criterion is judging — never merged indistinguishably with the plain
// written-answer criteria. Absent/"answer" renders nothing (today's look).
const APPLIES_TO_LABEL = { diagram: 'Diagram', calculation: 'Calculation' };

// "hash-map" -> "Hash Map" — the tooltip shows the real topic name, not a slug.
function topicLabel(tag) {
  return tag.split('-').map((w) => w[0]?.toUpperCase() + w.slice(1)).join(' ');
}

// FastAPI returns `detail` as a plain string for most 4xx/5xx here, but 402/429
// (credit + window limits) come back as structured objects — flatten so
// toast.error never gets handed a React child it can't render.
function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

const DIFFICULTY_COLOR = {
  Easy: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  Medium: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  Hard: 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30',
};

const MONACO_LANGUAGE = { python: 'python', javascript: 'javascript', cpp: 'cpp', java: 'java', sql: 'sql' };
const LANGUAGE_LABEL = { python: 'Python', javascript: 'JavaScript', cpp: 'C++', java: 'Java', sql: 'SQL' };

// A small renders-a-JSON-cell helper — SQL result rows can contain NULL,
// numbers, or strings, and every one of those needs to render as something
// visibly distinct (an empty string cell for NULL would look identical to
// an actual empty string).
function sqlCell(v) {
  if (v === null || v === undefined) return <span className="italic text-muted-foreground/70">NULL</span>;
  return String(v);
}

function SqlTable({ name, columns, rows }) {
  return (
    <div className="rounded-md border border-border overflow-x-auto">
      {name && <div className="px-2.5 py-1.5 text-xs font-medium border-b border-border bg-muted/40">{name}</div>}
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="border-b border-border">
            {columns.map((c) => (
              <th key={c} className="text-left px-2.5 py-1.5 font-medium text-muted-foreground">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={columns.length || 1} className="px-2.5 py-2 text-muted-foreground italic">(no rows)</td></tr>
          ) : (
            rows.map((row, i) => (
              <tr key={i} className="border-b border-border last:border-0">
                {row.map((v, j) => <td key={j} className="px-2.5 py-1.5">{sqlCell(v)}</td>)}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function Practice() {
  const [searchParams] = useSearchParams();
  const [problems, setProblems] = useState([]);
  const [problemId, setProblemId] = useState(null);
  const [problem, setProblem] = useState(null);
  const [language, setLanguage] = useState('python');
  const [code, setCode] = useState('');
  const [loadingProblem, setLoadingProblem] = useState(true);
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [resultMode, setResultMode] = useState(null); // 'run' | 'submit'
  const [error, setError] = useState('');
  const [submissions, setSubmissions] = useState(null);
  const [loadingSubmissions, setLoadingSubmissions] = useState(false);
  const [expandedSubmission, setExpandedSubmission] = useState(null);

  // MCQ-only state.
  const [selectedOption, setSelectedOption] = useState(null);
  const [mcqResult, setMcqResult] = useState(null);

  // Design-only state. `designDiagram`/`designCalculation` are only ever
  // rendered/submitted when the current problem opts in via
  // `supports_diagram`/`supports_calculation` — for every problem that
  // doesn't, these stay at their empty defaults and are never sent.
  // `designDiagram` holds whatever Excalidraw's own `onChange` last handed
  // back — `{elements, appState, files}` — not a react-flow node/edge graph;
  // it's rendered to a real PNG at submit time via `exportDiagramForSubmit`.
  const [designAnswer, setDesignAnswer] = useState('');
  const [designDiagram, setDesignDiagram] = useState({ elements: [], appState: null, files: null });
  const [designCalculation, setDesignCalculation] = useState('');
  const [designResult, setDesignResult] = useState(null);

  const questionType = problem?.question_type || 'code';

  // Load the problem list once, then select either the problem requested via
  // ?problem=<id> (e.g. a click-through from the Roadmap page) if it's a
  // real problem id, or the first problem otherwise.
  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get('/practice/problems');
        setProblems(data.items || []);
        const requested = searchParams.get('problem');
        const items = data.items || [];
        if (requested && items.some((p) => p.id === requested)) {
          setProblemId(requested);
        } else if (items.length) {
          setProblemId(items[0].id);
        } else {
          setLoadingProblem(false);
        }
      } catch (e) {
        setError(detailToString(e, 'Failed to load problems'));
        setLoadingProblem(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the selected problem's detail (statement + starter code).
  useEffect(() => {
    if (!problemId) return;
    setLoadingProblem(true);
    setResult(null);
    setError('');
    setSubmissions(null);
    setSelectedOption(null);
    setMcqResult(null);
    setDesignAnswer('');
    setDesignDiagram({ elements: [], appState: null, files: null });
    setDesignCalculation('');
    setDesignResult(null);
    (async () => {
      try {
        const { data } = await api.get(`/practice/problems/${problemId}`);
        setProblem(data);
        const firstLang = data.languages?.[0] || 'python';
        setLanguage(firstLang);
        setCode(data.starter_code?.[firstLang] || '');
      } catch (e) {
        setError(detailToString(e, 'Failed to load problem'));
      } finally {
        setLoadingProblem(false);
      }
    })();
  }, [problemId]);

  const changeLanguage = (lang) => {
    setLanguage(lang);
    // Swap in that language's starter code — but only if the editor still holds
    // the OLD language's untouched starter, so we never clobber in-progress work.
    const prevStarter = problem?.starter_code?.[language];
    if (!code || code === prevStarter) {
      setCode(problem?.starter_code?.[lang] || '');
    }
  };

  const resetStarter = () => {
    if (problem) setCode(problem.starter_code?.[language] || '');
  };

  const run = async () => {
    if (!problem || running || submitting) return;
    setRunning(true);
    setResult(null);
    setError('');
    try {
      const { data } = await api.post(`/practice/problems/${problem.id}/run`, { code, language });
      setResult(data);
      setResultMode('run');
      if (data.all_passed) toast.success(`Sample tests passed (${data.total}/${data.total}) — free, no credits used`);
      else toast.error(`${data.passed_count}/${data.total} sample tests passed`);
    } catch (e) {
      setError(detailToString(e, 'Run failed'));
      toast.error(detailToString(e, 'Run failed'));
    } finally {
      setRunning(false);
    }
  };

  const submit = async () => {
    if (!problem || submitting || running) return;
    setSubmitting(true);
    setResult(null);
    setError('');
    try {
      const { data } = await api.post(`/practice/problems/${problem.id}/submit`, { code, language });
      setResult(data);
      setResultMode('submit');
      setSubmissions(null); // stale now — refetch next time the tab is opened
      // wallet sidebar counter is updated automatically by the api.js response interceptor
      if (data.all_passed) toast.success(`All ${data.total} tests passed! -${data.credits_used} credits`);
      else toast.error(`${data.passed_count}/${data.total} tests passed — -${data.credits_used} credits`);
    } catch (e) {
      setError(detailToString(e, 'Submission failed'));
      toast.error(detailToString(e, 'Submission failed'));
    } finally {
      setSubmitting(false);
    }
  };

  const submitMcq = async () => {
    if (!problem || !selectedOption || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const { data } = await api.post(`/practice/problems/${problem.id}/submit-mcq`, {
        selected_option_id: selectedOption,
      });
      setMcqResult(data);
      if (data.passed) toast.success('Correct!');
      else toast.error('Not quite — see the correct answer below.');
    } catch (e) {
      setError(detailToString(e, 'Submission failed'));
      toast.error(detailToString(e, 'Submission failed'));
    } finally {
      setSubmitting(false);
    }
  };

  const submitDesign = async () => {
    if (!problem || !designAnswer.trim() || submitting) return;
    setSubmitting(true);
    setError('');
    setDesignResult(null);
    try {
      const payload = { answer_text: designAnswer };
      // Only sent for a problem that actually opted in — matches the
      // backend, which also ignores these fields for a problem that never
      // set supports_diagram/supports_calculation.
      if (problem.supports_diagram) {
        try {
          // Renders the Excalidraw scene to a real PNG + base64-encodes it
          // (see DesignDiagramCanvas.jsx) — this, not raw scene JSON, is
          // what the backend actually grades against now.
          payload.diagram = await exportDiagramForSubmit(designDiagram);
        } catch (exportErr) {
          // Never let a failed image export block the whole submission —
          // fall back to submitting without a diagram; the rubric already
          // scores a missing diagram low rather than erroring.
          console.error('Diagram export failed; submitting without a diagram image', exportErr);
        }
      }
      if (problem.supports_calculation && designCalculation.trim()) payload.calculation_text = designCalculation;
      const { data } = await api.post(`/practice/problems/${problem.id}/submit-design`, payload);
      setDesignResult(data);
      toast.success(`Graded: ${data.total_score}/${data.max_total_score} (${data.pct}%) — -${data.credits_used} credits`);
    } catch (e) {
      setError(detailToString(e, 'AI grading failed'));
      toast.error(detailToString(e, 'AI grading failed'));
    } finally {
      setSubmitting(false);
    }
  };

  const loadSubmissions = async () => {
    if (!problem || loadingSubmissions) return;
    setLoadingSubmissions(true);
    try {
      const { data } = await api.get(`/practice/problems/${problem.id}/submissions`);
      setSubmissions(data.items || []);
    } catch (e) {
      toast.error(detailToString(e, 'Failed to load submissions'));
    } finally {
      setLoadingSubmissions(false);
    }
  };

  const passSummary = useMemo(() => {
    if (!result) return null;
    return `${result.passed_count}/${result.total} passed`;
  }, [result]);

  const sqlResultEntry = questionType === 'sql' && result ? result.results?.[0] : null;

  return (
    <div className="max-w-[1400px] mx-auto p-6" data-testid="practice-page">
      <div className="mb-6 flex items-center gap-3">
        <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
          <Code2 className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Practice Engine</h1>
          <p className="text-sm text-muted-foreground">DSA, SQL, Logical Reasoning, Computer Networks, and System Design — practice against real graders.</p>
        </div>
      </div>

      {problems.length > 1 && (
        <div className="mb-4 flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Problem:</span>
          <Select value={problemId ?? undefined} onValueChange={setProblemId}>
            <SelectTrigger className="w-72" data-testid="practice-problem-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {problems.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.title} <span className="text-muted-foreground">· {p.path}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {error && !problem && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive" data-testid="practice-load-error">
          {error}
        </div>
      )}

      {loadingProblem && !problem && (
        <div className="flex items-center gap-2 text-muted-foreground text-sm py-12 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading problem…
        </div>
      )}

      {problem && (questionType === 'code' || questionType === 'sql') && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: problem statement */}
          <div className="rounded-lg border border-border bg-card p-5 space-y-4 lg:max-h-[calc(100vh-220px)] lg:overflow-y-auto" data-testid="practice-statement">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-semibold">{problem.title}</h2>
              <Badge variant="outline" className={DIFFICULTY_COLOR[problem.difficulty] || ''}>
                {problem.difficulty}
              </Badge>
              {questionType === 'sql' && (
                <Badge variant="outline" className="flex items-center gap-1 text-xs">
                  <Database className="h-3 w-3" /> SQL
                </Badge>
              )}
              {problem.tags?.length > 0 && (
                <span className="text-xs text-muted-foreground">Topics:</span>
              )}
              <TooltipProvider delayDuration={200}>
                {(problem.tags || []).map((t) => (
                  <Tooltip key={t}>
                    <TooltipTrigger asChild>
                      <Badge variant="secondary" className="text-xs cursor-default">{t}</Badge>
                    </TooltipTrigger>
                    <TooltipContent>{topicLabel(t)}</TooltipContent>
                  </Tooltip>
                ))}
              </TooltipProvider>
            </div>
            <Tabs defaultValue="description" onValueChange={(v) => { if (v === 'submissions' && submissions === null) loadSubmissions(); }}>
              <TabsList>
                <TabsTrigger value="description" data-testid="practice-tab-description">Description</TabsTrigger>
                <TabsTrigger value="solution" data-testid="practice-tab-solution">Solution</TabsTrigger>
                <TabsTrigger value="submissions" data-testid="practice-tab-submissions">Submissions</TabsTrigger>
              </TabsList>

              <TabsContent value="description" className="space-y-4">
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{problem.description}</ReactMarkdown>
                </div>

                {questionType === 'sql' && problem.tables?.length > 0 && (
                  <div data-testid="practice-sql-tables">
                    <div className="font-medium text-sm mb-1.5">Sample data:</div>
                    <div className="space-y-2">
                      {problem.tables.map((t) => (
                        <SqlTable key={t.name} name={t.name} columns={t.columns} rows={t.rows} />
                      ))}
                    </div>
                    {problem.order_sensitive && (
                      <p className="text-[11px] text-muted-foreground mt-1.5">
                        Row order matters for this problem — the same rows in a different order will be marked incorrect.
                      </p>
                    )}
                  </div>
                )}

                {(problem.examples || []).map((ex, i) => (
                  <div key={i} className="rounded-md border border-border bg-muted/40 p-3 text-sm" data-testid={`practice-example-${i}`}>
                    <div className="font-medium mb-1.5">Example {i + 1}:</div>
                    <div className="font-mono text-xs space-y-1">
                      <div><span className="text-muted-foreground">Input:</span> {ex.input}</div>
                      <div><span className="text-muted-foreground">Output:</span> {ex.output}</div>
                      {ex.explanation && (
                        <div><span className="text-muted-foreground">Explanation:</span> {ex.explanation}</div>
                      )}
                    </div>
                  </div>
                ))}

                {problem.constraints?.length > 0 && (
                  <div>
                    <div className="font-medium text-sm mb-1.5">Constraints:</div>
                    <ul className="font-mono text-xs text-muted-foreground space-y-1 list-disc list-inside">
                      {problem.constraints.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {problem.hints?.length > 0 && (
                  <div data-testid="practice-hints">
                    <div className="flex items-center gap-1.5 font-medium text-sm mb-1">
                      <Lightbulb className="h-4 w-4 text-amber-500" /> Hints
                    </div>
                    <Accordion type="multiple" className="w-full">
                      {problem.hints.map((h, i) => (
                        <AccordionItem key={i} value={`hint-${i}`}>
                          <AccordionTrigger className="text-sm py-2">Hint {i + 1}</AccordionTrigger>
                          <AccordionContent className="text-sm text-muted-foreground">{h}</AccordionContent>
                        </AccordionItem>
                      ))}
                    </Accordion>
                  </div>
                )}
              </TabsContent>

              <TabsContent value="solution" data-testid="practice-tab-solution-content" className="space-y-4">
                {problem.solution_writeup ? (
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{problem.solution_writeup}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No editorial written for this problem yet.</p>
                )}

                {problem.video_links?.length > 0 && (
                  <div data-testid="practice-video-links">
                    <div className="flex items-center gap-1.5 font-medium text-sm mb-2">
                      <Youtube className="h-4 w-4 text-red-500" /> Video walkthroughs
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                      {problem.video_links.map((v) => (
                        <a
                          key={v.video_id}
                          href={v.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded-md border border-border overflow-hidden hover:border-primary/50 transition-colors"
                        >
                          {v.thumbnail && <img src={v.thumbnail} alt="" className="w-full aspect-video object-cover" />}
                          <div className="p-2">
                            <div className="text-xs font-medium line-clamp-2">{v.title}</div>
                            <div className="text-[11px] text-muted-foreground mt-0.5">{v.channel}</div>
                          </div>
                        </a>
                      ))}
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-2">
                      Links to external YouTube videos, not affiliated with or verified by us.
                    </p>
                  </div>
                )}
              </TabsContent>

              <TabsContent value="submissions" data-testid="practice-tab-submissions-content">
                {loadingSubmissions ? (
                  <div className="flex items-center gap-2 text-muted-foreground text-sm py-6 justify-center">
                    <Loader2 className="h-4 w-4 animate-spin" /> Loading submissions…
                  </div>
                ) : !submissions?.length ? (
                  <div className="flex flex-col items-center gap-2 text-muted-foreground text-sm py-6">
                    <History className="h-5 w-5" />
                    No submissions yet — hit Submit once you've got something working.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {submissions.map((s) => (
                      <div key={s.id} className="rounded-md border border-border text-xs">
                        <button
                          type="button"
                          onClick={() => setExpandedSubmission(expandedSubmission === s.id ? null : s.id)}
                          className="w-full flex items-center justify-between gap-2 p-2.5 text-left hover:bg-muted/40"
                          data-testid={`practice-submission-${s.id}`}
                        >
                          <span className="flex items-center gap-2">
                            {s.all_passed ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                            ) : (
                              <XCircle className="h-3.5 w-3.5 text-rose-500 shrink-0" />
                            )}
                            <span className="font-medium">{s.passed_count}/{s.total} passed</span>
                            <Badge variant="outline" className="text-[10px]">{LANGUAGE_LABEL[s.language] || s.language}</Badge>
                          </span>
                          <span className="text-muted-foreground">{new Date(s.created_at).toLocaleString()}</span>
                        </button>
                        {expandedSubmission === s.id && (
                          <pre className="border-t border-border p-2.5 overflow-x-auto font-mono whitespace-pre">{s.code}</pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </div>

          {/* Right: editor + run + results */}
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-card overflow-hidden">
              <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
                {questionType === 'sql' ? (
                  <span className="text-sm font-medium px-1">SQL</span>
                ) : (
                  <Select value={language} onValueChange={changeLanguage}>
                    <SelectTrigger className="w-40 h-8" data-testid="practice-language-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(problem.languages || []).map((l) => (
                        <SelectItem key={l} value={l}>{LANGUAGE_LABEL[l] || l}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={resetStarter} data-testid="practice-reset-btn">
                    Reset
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={run}
                    disabled={running || submitting}
                    data-testid="practice-run-btn"
                    title={questionType === 'sql' ? 'Runs your query against the sample database — free, not recorded' : 'Runs only the sample tests shown in Examples — free, not recorded'}
                  >
                    {running ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Play className="h-4 w-4 mr-2" />}
                    Run
                  </Button>
                  <Button
                    size="sm"
                    onClick={submit}
                    disabled={submitting || running}
                    data-testid="practice-submit-btn"
                    title="Runs the real grading and counts toward your progress"
                  >
                    {submitting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <CheckCircle2 className="h-4 w-4 mr-2" />}
                    Submit
                  </Button>
                </div>
              </div>
              <Editor
                height="420px"
                language={MONACO_LANGUAGE[questionType === 'sql' ? 'sql' : language] || 'plaintext'}
                theme="vs-dark"
                value={code}
                onChange={(v) => setCode(v ?? '')}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                }}
                data-testid="practice-editor"
              />
            </div>

            {error && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive" data-testid="practice-submit-error">
                {error}
              </div>
            )}

            {result && questionType === 'code' && (
              <div className="rounded-lg border border-border bg-card p-4 space-y-3" data-testid="practice-results">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 font-medium">
                    {result.all_passed ? (
                      <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                    ) : (
                      <XCircle className="h-5 w-5 text-rose-500" />
                    )}
                    <span data-testid="practice-pass-summary">{passSummary}</span>
                  </div>
                  {resultMode === 'submit' ? (
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Coins className="h-3.5 w-3.5" /> -{result.credits_used} credits · balance {result.balance}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">sample tests only · free</span>
                  )}
                </div>
                <div className="space-y-2">
                  {result.results.map((r) => (
                    <div
                      key={r.index}
                      className={`rounded-md border p-3 text-xs ${r.passed ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-rose-500/30 bg-rose-500/5'}`}
                      data-testid={`practice-test-${r.index}`}
                    >
                      <div className="flex items-center gap-2 font-medium mb-1">
                        {r.passed ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> : <XCircle className="h-3.5 w-3.5 text-rose-500" />}
                        Test case {r.index + 1}
                        {r.hidden && (
                          <span className="flex items-center gap-1 text-muted-foreground font-normal ml-1">
                            <Lock className="h-3 w-3" /> hidden
                          </span>
                        )}
                      </div>
                      {r.hidden ? (
                        <div className="text-muted-foreground italic">
                          {r.passed ? 'Passed.' : 'Failed — details are hidden for this test case.'}
                        </div>
                      ) : (
                        <div className="font-mono text-muted-foreground space-y-0.5">
                          <div>input: {JSON.stringify(r.input)}</div>
                          <div>expected: {JSON.stringify(r.expected)}</div>
                          <div>actual: {r.actual_raw || '(no output)'}</div>
                          {r.stderr && <div className="text-rose-500 whitespace-pre-wrap">{r.stderr.slice(0, 500)}</div>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {result && questionType === 'sql' && sqlResultEntry && (
              <div className="rounded-lg border border-border bg-card p-4 space-y-3" data-testid="practice-sql-results">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 font-medium">
                    {sqlResultEntry.passed ? (
                      <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                    ) : (
                      <XCircle className="h-5 w-5 text-rose-500" />
                    )}
                    <span>{sqlResultEntry.passed ? 'Correct' : 'Incorrect'}</span>
                  </div>
                  {resultMode === 'submit' ? (
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Coins className="h-3.5 w-3.5" /> -{result.credits_used} credits · balance {result.balance}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">free — not recorded</span>
                  )}
                </div>

                {sqlResultEntry.error ? (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs font-mono text-destructive whitespace-pre-wrap">
                    {sqlResultEntry.error}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <div className="text-xs font-medium mb-1.5 text-muted-foreground">Your result</div>
                      <SqlTable columns={sqlResultEntry.columns} rows={sqlResultEntry.actual_rows} />
                    </div>
                    <div>
                      <div className="text-xs font-medium mb-1.5 text-muted-foreground">Expected result</div>
                      <SqlTable columns={sqlResultEntry.columns} rows={sqlResultEntry.expected_rows} />
                    </div>
                  </div>
                )}
                {sqlResultEntry.order_sensitive && (
                  <p className="text-[11px] text-muted-foreground">Row order matters for this problem.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* MCQ: no code editor at all — options + immediate feedback. */}
      {problem && questionType === 'mcq' && (
        <div className="max-w-2xl mx-auto rounded-lg border border-border bg-card p-6 space-y-5" data-testid="practice-mcq">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-xl font-semibold">{problem.title}</h2>
            <Badge variant="outline" className={DIFFICULTY_COLOR[problem.difficulty] || ''}>{problem.difficulty}</Badge>
            <Badge variant="outline" className="flex items-center gap-1 text-xs"><ListChecks className="h-3 w-3" /> Multiple Choice</Badge>
          </div>
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{problem.description}</ReactMarkdown>
          </div>

          <div className="space-y-2" data-testid="practice-mcq-options">
            {(problem.options || []).map((opt) => {
              const isSelected = selectedOption === opt.id;
              const isCorrect = mcqResult && opt.id === mcqResult.correct_option_id;
              const isWrongPick = mcqResult && isSelected && !mcqResult.passed;
              return (
                <button
                  key={opt.id}
                  type="button"
                  disabled={!!mcqResult}
                  onClick={() => setSelectedOption(opt.id)}
                  data-testid={`practice-mcq-option-${opt.id}`}
                  className={`w-full flex items-center gap-3 rounded-md border px-3.5 py-2.5 text-left text-sm transition-colors ${
                    mcqResult
                      ? isCorrect
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : isWrongPick
                          ? 'border-rose-500/40 bg-rose-500/10'
                          : 'border-border opacity-70'
                      : isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:bg-accent/50'
                  }`}
                >
                  <span
                    className={`h-4 w-4 rounded-full border shrink-0 flex items-center justify-center ${
                      isSelected ? 'border-primary' : 'border-muted-foreground/40'
                    }`}
                  >
                    {isSelected && <span className="h-2 w-2 rounded-full bg-primary" />}
                  </span>
                  <span className="flex-1">{opt.text}</span>
                  {mcqResult && isCorrect && <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />}
                  {mcqResult && isWrongPick && <XCircle className="h-4 w-4 text-rose-500 shrink-0" />}
                </button>
              );
            })}
          </div>

          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
          )}

          {!mcqResult ? (
            <Button onClick={submitMcq} disabled={!selectedOption || submitting} data-testid="practice-mcq-submit-btn">
              {submitting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Submit Answer
            </Button>
          ) : (
            <div
              className={`rounded-md border p-3 text-sm flex items-center gap-2 ${mcqResult.passed ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400' : 'border-rose-500/30 bg-rose-500/5 text-rose-600 dark:text-rose-400'}`}
              data-testid="practice-mcq-result"
            >
              {mcqResult.passed ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
              {mcqResult.passed ? 'Correct!' : 'Not quite — the correct option is highlighted above.'}
              <span className="ml-auto text-xs text-muted-foreground">free · no credits used</span>
            </div>
          )}

          {problem.solution_writeup && (
            <Accordion type="single" collapsible>
              <AccordionItem value="explanation">
                <AccordionTrigger className="text-sm">Explanation</AccordionTrigger>
                <AccordionContent>
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{problem.solution_writeup}</ReactMarkdown>
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}
        </div>
      )}

      {/* Design (LLD/HLD): large free-text answer, graded by an LLM against a rubric. */}
      {problem && questionType === 'design' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="rounded-lg border border-border bg-card p-5 space-y-4 lg:max-h-[calc(100vh-220px)] lg:overflow-y-auto" data-testid="practice-design-statement">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-semibold">{problem.title}</h2>
              <Badge variant="outline" className={DIFFICULTY_COLOR[problem.difficulty] || ''}>{problem.difficulty}</Badge>
              <Badge variant="outline" className="flex items-center gap-1 text-xs"><PencilRuler className="h-3 w-3" /> System Design</Badge>
            </div>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{problem.description}</ReactMarkdown>
            </div>

            {problem.hints?.length > 0 && (
              <div data-testid="practice-hints">
                <div className="flex items-center gap-1.5 font-medium text-sm mb-1">
                  <Lightbulb className="h-4 w-4 text-amber-500" /> Hints
                </div>
                <Accordion type="multiple" className="w-full">
                  {problem.hints.map((h, i) => (
                    <AccordionItem key={i} value={`hint-${i}`}>
                      <AccordionTrigger className="text-sm py-2">Hint {i + 1}</AccordionTrigger>
                      <AccordionContent className="text-sm text-muted-foreground">{h}</AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </div>
            )}

            <div>
              <div className="font-medium text-sm mb-1.5">Grading rubric:</div>
              <div className="space-y-1.5" data-testid="practice-design-rubric">
                {(problem.rubric || []).map((c) => (
                  <div key={c.criterion} className="rounded-md border border-border p-2.5 text-xs">
                    <div className="flex items-center justify-between font-medium gap-2">
                      <span className="flex items-center gap-1.5">
                        {c.criterion}
                        {APPLIES_TO_LABEL[c.applies_to] && (
                          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                            {APPLIES_TO_LABEL[c.applies_to]}
                          </Badge>
                        )}
                      </span>
                      <span className="text-muted-foreground shrink-0">max {c.max_score}</span>
                    </div>
                    <div className="text-muted-foreground mt-0.5">{c.description}</div>
                  </div>
                ))}
              </div>
            </div>

            {problem.solution_writeup && (
              <Accordion type="single" collapsible>
                <AccordionItem value="editorial">
                  <AccordionTrigger className="text-sm">Key points a strong answer should hit</AccordionTrigger>
                  <AccordionContent>
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{problem.solution_writeup}</ReactMarkdown>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            )}
          </div>

          <div className="space-y-4">
            {problem.supports_diagram && (
              <div className="rounded-lg border border-border bg-card p-4">
                {/* Keyed by problem id so switching problems remounts the
                    canvas (a real reset) rather than relying on a prop change
                    Excalidraw's `initialData` deliberately ignores after mount. */}
                <DesignDiagramCanvas key={problem.id} initialDiagram={designDiagram} onChange={setDesignDiagram} />
              </div>
            )}

            {problem.supports_calculation && (
              <div className="rounded-lg border border-border bg-card p-4">
                <CalculationScratchpad value={designCalculation} onChange={setDesignCalculation} />
              </div>
            )}

            <div className="rounded-lg border border-border bg-card p-4 space-y-3">
              <Textarea
                value={designAnswer}
                onChange={(e) => setDesignAnswer(e.target.value)}
                placeholder="Write your design here — cover the architecture, data model, key trade-offs, and edge cases the rubric asks about..."
                className="min-h-[360px] font-mono text-sm"
                data-testid="practice-design-textarea"
              />
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Graded by AI against the rubric shown on the left — credit-gated.</span>
                <Button
                  onClick={submitDesign}
                  disabled={!designAnswer.trim() || submitting}
                  data-testid="practice-design-submit-btn"
                >
                  {submitting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                  Submit for AI Grading
                </Button>
              </div>
            </div>

            {error && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive" data-testid="practice-submit-error">
                {error}
              </div>
            )}

            {designResult && (
              <div className="rounded-lg border border-border bg-card p-4 space-y-3" data-testid="practice-design-result">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 font-medium">
                    {designResult.all_passed ? (
                      <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                    ) : (
                      <XCircle className="h-5 w-5 text-amber-500" />
                    )}
                    <span>{designResult.total_score}/{designResult.max_total_score} ({designResult.pct}%)</span>
                  </div>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Coins className="h-3.5 w-3.5" /> -{designResult.credits_used} credits · balance {designResult.balance}
                  </span>
                </div>

                <div className="space-y-2">
                  {(designResult.criteria || []).map((c, i) => (
                    <div key={i} className="rounded-md border border-border p-3 text-xs space-y-1" data-testid={`practice-design-criterion-${i}`}>
                      <div className="flex items-center justify-between font-medium gap-2">
                        <span className="flex items-center gap-1.5">
                          {c.criterion}
                          {APPLIES_TO_LABEL[c.applies_to] && (
                            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                              {APPLIES_TO_LABEL[c.applies_to]}
                            </Badge>
                          )}
                        </span>
                        <span className="shrink-0">{c.score}/{c.max_score}</span>
                      </div>
                      <div className="text-muted-foreground">{c.feedback}</div>
                    </div>
                  ))}
                </div>

                {designResult.overall_feedback && (
                  <div className="rounded-md border border-primary/20 bg-primary/5 p-3 text-xs">
                    <div className="font-medium mb-1">Overall feedback</div>
                    <div className="text-muted-foreground">{designResult.overall_feedback}</div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
