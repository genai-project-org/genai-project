import { useState } from 'react';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Loader2, Briefcase, MapPin, IndianRupee, ExternalLink, GraduationCap, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function Career() {
  return (
    <div className="max-w-6xl mx-auto p-6" data-testid="career-page">
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Briefcase className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Career Intelligence</h1>
            <p className="text-sm text-muted-foreground">India-focused job search + AI-generated learning paths (cached to save credits).</p>
          </div>
        </div>
      </div>
      <Tabs defaultValue="jobs">
        <TabsList>
          <TabsTrigger value="jobs" data-testid="career-tab-jobs"><Briefcase className="h-4 w-4 mr-2" />Jobs</TabsTrigger>
          <TabsTrigger value="path" data-testid="career-tab-path"><GraduationCap className="h-4 w-4 mr-2" />Learning Path</TabsTrigger>
        </TabsList>
        <TabsContent value="jobs"><Jobs /></TabsContent>
        <TabsContent value="path"><LearningPath /></TabsContent>
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
