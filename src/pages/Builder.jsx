import { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import api from '@/lib/api';
import { setWalletBalance } from '@/store/slices/uiSlice';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import {
  Loader2, Sparkles, Plus, Code2, Play, Share2, Github, Wand2, Trash2, FileCode,
  Copy, Check, ExternalLink, RefreshCcw
} from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

export default function Builder() {
  const [projects, setProjects] = useState([]);
  const [active, setActive] = useState(null);
  const [activeFileIdx, setActiveFileIdx] = useState(0);
  const [previewHtml, setPreviewHtml] = useState('');
  const [saving, setSaving] = useState(false);
  const [refining, setRefining] = useState(false);
  const [refineText, setRefineText] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [showGithub, setShowGithub] = useState(false);
  const [shareUrl, setShareUrl] = useState('');
  const [shareCopied, setShareCopied] = useState(false);
  const [ghConnected, setGhConnected] = useState(false);
  const dispatch = useDispatch();
  const previewRef = useRef(null);

  const load = async () => {
    const { data } = await api.get('/builder/projects');
    setProjects(data.items || []);
  };
  const loadGh = async () => {
    try { const { data } = await api.get('/builder/github/status'); setGhConnected(data.connected); } catch {}
  };
  useEffect(() => { load(); loadGh(); }, []);

  const openProject = async (id) => {
    const { data } = await api.get(`/builder/projects/${id}`);
    setActive(data); setActiveFileIdx(0); setPreviewHtml(''); setShareUrl('');
    // Fetch preview
    const p = await api.get(`/builder/projects/${id}/preview`);
    setPreviewHtml(p.data.html || '');
  };

  const currentFile = active?.files?.[activeFileIdx];

  const updateFile = (content) => {
    if (!active) return;
    const updated = { ...active, files: active.files.map((f, i) => i === activeFileIdx ? { ...f, content } : f) };
    setActive(updated);
  };

  const saveFiles = async () => {
    if (!active) return;
    setSaving(true);
    try {
      await api.patch(`/builder/projects/${active.id}/files`, { files: active.files });
      const p = await api.get(`/builder/projects/${active.id}/preview`);
      setPreviewHtml(p.data.html || '');
      toast.success('Saved');
    } catch (e) { toast.error(e.response?.data?.detail || 'Save failed'); }
    finally { setSaving(false); }
  };

  const refresh = async () => {
    if (!active) return;
    const p = await api.get(`/builder/projects/${active.id}/preview`);
    setPreviewHtml(p.data.html || '');
    toast.success('Preview refreshed');
  };

  const doRefine = async () => {
    if (!active || !refineText.trim()) return;
    setRefining(true);
    try {
      const { data } = await api.post(`/builder/projects/${active.id}/refine`, { instruction: refineText });
      const updated = { ...active, files: data.files };
      setActive(updated); setActiveFileIdx(0);
      dispatch(setWalletBalance(data.balance));
      toast.success('Refined');
      const p = await api.get(`/builder/projects/${active.id}/preview`);
      setPreviewHtml(p.data.html || '');
      setRefineText('');
    } catch (e) { toast.error(e.response?.data?.detail || 'Refine failed'); }
    finally { setRefining(false); }
  };

  const doShare = async () => {
    if (!active) return;
    try {
      const { data } = await api.post(`/builder/projects/${active.id}/share`);
      setShareUrl(data.share_url);
      toast.success('Share URL created (7-day)');
    } catch (e) { toast.error(e.response?.data?.detail || 'Share failed'); }
  };

  const copyShare = () => {
    if (!shareUrl) return;
    navigator.clipboard.writeText(shareUrl);
    setShareCopied(true); setTimeout(() => setShareCopied(false), 1500);
  };

  const deleteProject = async (id) => {
    if (!window.confirm('Delete this project?')) return;
    await api.delete(`/builder/projects/${id}`);
    if (active?.id === id) { setActive(null); setPreviewHtml(''); }
    load();
  };

  return (
    <div className="h-full flex" data-testid="builder-page">
      {/* Left: projects list */}
      <div className="w-[260px] border-r border-border flex flex-col">
        <div className="p-3 border-b border-border">
          <Button className="w-full gap-2" onClick={() => setShowCreate(true)} data-testid="builder-new-project-btn">
            <Plus className="h-4 w-4" /> New Project
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1" data-testid="builder-project-list">
          {projects.length === 0 && <div className="text-xs text-muted-foreground text-center py-6">No projects yet.</div>}
          {projects.map((p) => (
            <div key={p.id} data-testid="builder-project-item"
              className={cn('group flex items-center gap-2 rounded-md px-2 py-2 cursor-pointer text-sm', active?.id === p.id ? 'bg-accent' : 'hover:bg-accent/60')}
              onClick={() => openProject(p.id)}
            >
              <Code2 className="h-3.5 w-3.5 flex-shrink-0 text-primary" />
              <span className="truncate flex-1">{p.name}</span>
              <button onClick={(e) => { e.stopPropagation(); deleteProject(p.id); }} className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive p-0.5">
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Middle + right: only when a project is active */}
      {!active ? (
        <div className="flex-1 flex items-center justify-center px-6">
          <div className="text-center max-w-md">
            <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mx-auto mb-6">
              <Code2 className="h-7 w-7 text-primary" />
            </div>
            <h2 className="font-display text-3xl font-medium">Code Builder</h2>
            <p className="text-sm text-muted-foreground mt-2">
              Describe an app. supercreator drops a working project you can preview, edit, share, or push to GitHub.
            </p>
            <div className="mt-6 flex flex-wrap gap-2 justify-center">
              <Button onClick={() => setShowCreate(true)} className="gap-2"><Plus className="h-4 w-4" /> New Project</Button>
            </div>
            <div className="mt-6 text-xs text-muted-foreground">Every prompt is cached — repeat requests are free.</div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex min-w-0">
          {/* File tree + editor */}
          <div className="w-[45%] border-r border-border flex flex-col min-w-0">
            <div className="border-b border-border px-3 py-2 flex items-center gap-2">
              <span className="font-medium truncate flex-1 text-sm">{active.name}</span>
              <Button size="sm" variant="ghost" onClick={saveFiles} disabled={saving} data-testid="builder-save-btn">
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
              </Button><Button size="sm" variant="outline" onClick={() => setShowGithub(true)} className="gap-1.5" data-testid="builder-github-btn">
                <Github className="h-3.5 w-3.5" /> Push
              </Button>
            </div>
            <div className="flex border-b border-border overflow-x-auto">
              {active.files.map((f, i) => (
                <button key={i} onClick={() => setActiveFileIdx(i)} data-testid="builder-file-tab"
                  className={cn('px-3 py-2 text-xs whitespace-nowrap border-r border-border flex items-center gap-1.5',
                    i === activeFileIdx ? 'bg-background text-foreground' : 'bg-[hsl(var(--surface))] text-muted-foreground hover:text-foreground')}>
                  <FileCode className="h-3 w-3" />{f.path}
                </button>
              ))}
            </div>
            <Textarea
              data-testid="builder-code-editor"
              value={currentFile?.content || ''}
              onChange={(e) => updateFile(e.target.value)}
              spellCheck={false}
              className="flex-1 rounded-none border-0 font-mono text-xs resize-none focus-visible:ring-0 leading-relaxed"
            />
            <div className="border-t border-border p-3 space-y-2">
              <div className="flex items-center gap-2">
                <Wand2 className="h-4 w-4 text-primary flex-shrink-0" />
                <span className="text-xs font-medium">Refine with AI</span>
              </div>
              <div className="flex gap-2">
                <Input
                  value={refineText}
                  onChange={(e) => setRefineText(e.target.value)}
                  placeholder="e.g. Add a dark mode toggle in the top-right"
                  data-testid="builder-refine-input"
                  onKeyDown={(e) => e.key === 'Enter' && doRefine()}
                />
                <Button onClick={doRefine} disabled={refining || !refineText.trim()} data-testid="builder-refine-btn">
                  {refining ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </div>
          {/* Preview */}
          <div className="flex-1 flex flex-col min-w-0 bg-white">
            <div className="border-b border-border px-3 py-2 flex items-center gap-2 bg-background">
              <Play className="h-4 w-4 text-primary" />
              <span className="text-xs font-medium">Live Preview</span>
              <div className="flex-1" />
              <Button size="sm" variant="ghost" onClick={refresh} className="gap-1.5" data-testid="builder-refresh-btn">
                <RefreshCcw className="h-3.5 w-3.5" /> Refresh
              </Button>
              <Button size="sm" variant="outline" onClick={doShare} className="gap-1.5" data-testid="builder-share-btn">
                <Share2 className="h-3.5 w-3.5" /> Share
              </Button>
            </div>
            {shareUrl && (
              <div className="border-b border-border px-3 py-2 bg-primary/5 flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">Public URL (7 days):</span>
                <a href={shareUrl} target="_blank" rel="noreferrer" className="truncate text-primary hover:underline flex-1" data-testid="builder-share-url">
                  {shareUrl.split('?')[0]}
                </a>
                <button onClick={copyShare} className="p-1 hover:bg-accent rounded" data-testid="builder-share-copy">
                  {shareCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                </button>
                <a href={shareUrl} target="_blank" rel="noreferrer" className="p-1 hover:bg-accent rounded">
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            )}
            <iframe
              ref={previewRef}
              srcDoc={previewHtml}
              data-testid="builder-preview-iframe"
              sandbox="allow-scripts allow-forms allow-popups allow-modals"
              className="flex-1 w-full border-0 bg-white"
              title="Preview"
            />
          </div>
        </div>
      )}

      <CreateDialog open={showCreate} onOpenChange={setShowCreate} onCreated={async (p) => { await load(); openProject(p.id); }} dispatch={dispatch} />
      <GithubDialog open={showGithub} onOpenChange={setShowGithub} project={active} connected={ghConnected} onDone={() => { loadGh(); }} />
    </div>
  );
}

function CreateDialog({ open, onOpenChange, onCreated, dispatch }) {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const submit = async () => {
    if (prompt.trim().length < 8) return toast.error('Describe the app (at least 8 chars)');
    setLoading(true);
    try {
      const { data } = await api.post('/builder/projects', { prompt });
      if (data.balance != null) dispatch(setWalletBalance(data.balance));
      toast.success('Ready');
      onOpenChange(false); setPrompt('');
      onCreated(data.project);
    } catch (e) { toast.error(e.response?.data?.detail || 'Create failed'); }
    finally { setLoading(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="builder-create-dialog">
        <DialogHeader>
          <DialogTitle>New Project</DialogTitle>
          <DialogDescription>Describe what to build. Repeat prompts are free.</DialogDescription>
        </DialogHeader>
        <Textarea
          data-testid="builder-create-prompt"
          rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Build a landing page for a plant-based food startup with hero, features, testimonials, and email signup form"
        />
        <DialogFooter>
          <Button data-testid="builder-create-submit" onClick={submit} disabled={loading || prompt.trim().length < 8}>
            {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Sparkles className="h-4 w-4 mr-2" />}
            Generate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function GithubDialog({ open, onOpenChange, project, connected, onDone }) {
  const [pat, setPat] = useState('');
  const [repo, setRepo] = useState('');
  const [commit, setCommit] = useState('supercreator.ai Builder push');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const submit = async () => {
    if (!project) return;
    if (!repo.includes('/')) return toast.error('Repo must be `owner/repo`');
    setLoading(true); setResult(null);
    try {
      const body = { repo, commit_message: commit, save_pat: true };
      if (pat.trim()) body.pat = pat.trim();
      const { data } = await api.post(`/builder/projects/${project.id}/github/push`, body);
      setResult(data);
      toast.success(`Pushed ${data.pushed.length} files`);
      onDone && onDone();
    } catch (e) { toast.error(e.response?.data?.detail || 'Push failed'); }
    finally { setLoading(false); }
  };
  const disconnect = async () => {
    await api.delete('/builder/github/disconnect');
    onDone && onDone();
    toast.success('Disconnected');
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="builder-github-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Github className="h-4 w-4" /> Push to GitHub</DialogTitle>
          <DialogDescription>
            {connected ? 'PAT is stored (encrypted). Leave blank to reuse.' : 'Paste a GitHub PAT with repo scope. Stored encrypted.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input placeholder="Personal Access Token (github.com/settings/tokens)" value={pat} onChange={(e) => setPat(e.target.value)} type="password" data-testid="builder-github-pat" />
          <Input placeholder="owner/repo (must exist, empty is OK)" value={repo} onChange={(e) => setRepo(e.target.value)} data-testid="builder-github-repo" />
          <Input placeholder="Commit message" value={commit} onChange={(e) => setCommit(e.target.value)} />
          {connected && <Button variant="ghost" size="sm" onClick={disconnect} className="text-destructive">Disconnect saved PAT</Button>}
          {result && (
            <div className="rounded-md bg-primary/5 border border-primary/20 p-3 text-xs">
              <div>Pushed: {result.pushed.length} files</div>
              {result.errors.length > 0 && <div className="text-destructive">Errors: {result.errors.length}</div>}
              <a href={result.repo_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">{result.repo_url}</a>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={loading || !repo.includes('/')} data-testid="builder-github-push-btn">
            {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Github className="h-4 w-4 mr-2" />}
            Push
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
