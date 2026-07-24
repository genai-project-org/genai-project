import { useCallback, useEffect, useState } from 'react';
import api from '@/lib/api';
import { studioStore, useStudioStore } from '@/lib/studioStore';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { Loader2, Sparkles, ImageIcon, FileText, Download, Video as VideoIcon, Link as LinkIcon, History as HistoryIcon } from 'lucide-react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// FastAPI validation errors and our rate-limit middleware return `detail` as
// an object/array — passing that raw to `toast.error()` throws "Objects are
// not valid as a React child" and unmounts the whole page. Always coerce.
function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

export default function Studio() {
  const [tab, setTab] = useState('summarize');
  // When leaving the Studio screen, clear any *idle* modules so the form
  // starts empty next visit. Any generation that's still running is
  // preserved so the user can rejoin it.
  useEffect(() => {
    return () => { studioStore.resetIdle(); };
  }, []);
  return (
    <div className="max-w-5xl mx-auto p-6" data-testid="studio-page">
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Sparkles className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">AI Studio</h1>
            <p className="text-sm text-muted-foreground">Summarize text or any web link, generate images, or produce short videos with Google Veo 3.1.</p>
          </div>
        </div>
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="studio-tabs">
          <TabsTrigger value="summarize" data-testid="studio-tab-summarize"><FileText className="h-4 w-4 mr-2" />Summarize</TabsTrigger>
          <TabsTrigger value="image" data-testid="studio-tab-image"><ImageIcon className="h-4 w-4 mr-2" />Image</TabsTrigger>
          <TabsTrigger value="video" data-testid="studio-tab-video"><VideoIcon className="h-4 w-4 mr-2" />Video</TabsTrigger>
          <TabsTrigger value="history" data-testid="studio-tab-history"><HistoryIcon className="h-4 w-4 mr-2" />History</TabsTrigger>
        </TabsList>
        <TabsContent value="summarize"><Summarize /></TabsContent>
        <TabsContent value="image"><ImageGen /></TabsContent>
        <TabsContent value="video"><VideoGen /></TabsContent>
        <TabsContent value="history"><StudioHistory onOpen={setTab} /></TabsContent>
      </Tabs>
    </div>
  );
}

function Summarize() {
  const state = useStudioStore('sum');
  const [text, setText] = useState(state.text || '');
  const [url, setUrl] = useState(state.url || '');
  const [style, setStyle] = useState(state.style || 'default');
  const [models, setModels] = useState([]);
  const [model, setModel] = useState(state.model || null);
  const busy = state.status === 'running';
  const otherBusy = studioStore.anyRunning() && !busy;

  useEffect(() => {
    api.get('/chat/models').then(({ data }) => {
      setModels(data.items);
      setModel((m) => m ?? (data.items.find((x) => x.default)?.id ?? data.items[0]?.id));
    }).catch(() => { });
  }, []);

  const run = async () => {
    if (studioStore.anyRunning()) return;
    if (text.trim().length < 20 && !url.trim()) return;
    studioStore.begin('sum', { text, url, style, model });
    try {
      const { data } = await api.post('/studio/summarize', {
        text: text.trim() || undefined,
        url: url.trim() || undefined,
        style,
        model,
      });
      studioStore.complete('sum', { result: data.summary });
    } catch (e) {
      studioStore.fail('sum', detailToString(e, 'Summarize failed'));
      toast.error(detailToString(e, 'Summarize failed'));
    }
  };

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <Textarea data-testid="studio-summarize-input" value={text} onChange={(e) => setText(e.target.value)}
                  placeholder="Paste content, notes or an article here..." rows={7} />
        <div className="flex items-center gap-2">
          <LinkIcon className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Or a website / article link:</span>
        </div>
        <Input value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder="https://example.com/article" data-testid="studio-summarize-url" />
        {models.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Model:</span>
            <select
              value={model ?? ''}
              onChange={(e) => setModel(e.target.value)}
              title={models.find((m) => m.id === model)?.description}
              className="text-xs rounded-lg border border-border bg-card px-2.5 py-1.5 text-foreground focus:outline-none focus:border-primary/50 cursor-pointer"
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name} — {m.label}</option>
              ))}
            </select>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {['default', 'eli5', 'executive'].map((s) => (
            <button type="button" key={s} onClick={() => setStyle(s)}
              className={`px-3 py-1.5 text-xs rounded-full border transition ${style === s ? 'border-primary text-primary bg-primary/10' : 'border-border text-muted-foreground hover:text-foreground'}`}>
              {s === 'default' ? 'Default' : s === 'eli5' ? 'ELI5' : 'Executive'}
            </button>
          ))}
          <div className="flex-1" />
          <Button data-testid="studio-summarize-btn" onClick={run} disabled={busy || otherBusy || (text.trim().length < 20 && !url.trim())}>
            {busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FileText className="h-4 w-4 mr-2" />}
            {busy ? 'Summarising…' : 'Summarize'}
          </Button>
        </div>
        {otherBusy && <p className="text-xs text-center text-muted-foreground">Another generation is running — finish it first.</p>}
      </div>

      {busy && (
        <div className="rounded-lg border border-border bg-card p-4 space-y-2">
          <Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-3/4" />
        </div>
      )}
      {state.status === 'done' && state.result && (
        <div className="rounded-lg border border-border bg-card p-4 prose prose-invert prose-sm max-w-none"
             data-testid="studio-summarize-result">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{state.result}</ReactMarkdown>
        </div>
      )}
      {state.status === 'error' && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-4 text-sm text-red-400">{state.error}</div>
      )}
    </div>
  );
}

function ImageGen() {
  const state = useStudioStore('img');
  const [prompt, setPrompt] = useState(state.prompt || '');
  const [artStyle, setArtStyle] = useState(state.artStyle || 'realistic');
  const [aspect, setAspect] = useState(state.aspect || 'square');
  const [quality, setQuality] = useState(state.quality || 'low');
  const busy = state.status === 'running';
  const otherBusy = studioStore.anyRunning() && !busy;

  const run = async () => {
    if (studioStore.anyRunning()) return;
    if (prompt.trim().length < 3) return;
    const fullPrompt = `${prompt.trim()}. Style: ${artStyle}. Aspect: ${aspect}. High visual fidelity, clean composition.`;
    studioStore.begin('img', { prompt, artStyle, aspect, quality });
    try {
      const { data } = await api.post('/studio/image', { prompt: fullPrompt, quality, n: 1 });
      studioStore.complete('img', { images: data.images });
    } catch (e) {
      studioStore.fail('img', detailToString(e, 'Image generation failed'));
      toast.error(detailToString(e, 'Image generation failed'));
    }
  };

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <Input data-testid="studio-image-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)}
               placeholder="A calm sunset over a mountain lake..." className="h-11" />
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Model:</span>
          <span className="px-3 py-1 text-xs rounded-full border border-primary text-primary bg-primary/10">GPT Image 1</span>
        </div>
        <ChipRow label="Style" options={['realistic', 'cinematic', 'anime', 'watercolor', 'pixel-art', '3D render']} value={artStyle} onChange={setArtStyle} />
        <ChipRow label="Aspect" options={['square', 'portrait', 'landscape']} value={aspect} onChange={setAspect} />
        <ChipRow label="Quality" options={['low', 'medium', 'high']} value={quality} onChange={setQuality} />
        <div className="flex justify-end">
          <Button data-testid="studio-image-btn" onClick={run} disabled={busy || otherBusy || prompt.trim().length < 3}>
            {busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <ImageIcon className="h-4 w-4 mr-2" />}
            {busy ? 'Rendering…' : 'Generate image'}
          </Button>
        </div>
        {otherBusy && <p className="text-xs text-center text-muted-foreground">Another generation is running — finish it first.</p>}
      </div>

      {busy && (
        <Skeleton className={`w-full rounded-lg ${aspect === 'portrait' ? 'aspect-[3/4]' : aspect === 'landscape' ? 'aspect-[16/9]' : 'aspect-square'}`} />
      )}
      {state.status === 'done' && (state.images || []).map((im, i) => (
        <div key={i} className="rounded-lg border border-border bg-card overflow-hidden">
          <img src={im.url} alt="" className="w-full block" />
          <div className="p-3 flex justify-end">
            <a href={im.url} download="iema-image.png" target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
               data-testid={`studio-image-save-${i}`}>
              <Download className="h-3.5 w-3.5" /> Save
            </a>
          </div>
        </div>
      ))}
      {state.status === 'error' && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-4 text-sm text-red-400">{state.error}</div>
      )}
    </div>
  );
}

function VideoGen() {
  const state = useStudioStore('vid');
  const [prompt, setPrompt] = useState(state.prompt || '');
  const [videoStyle, setVideoStyle] = useState(state.videoStyle || 'cinematic');
  const [motion, setMotion] = useState(state.motion || 'medium');
  const [model, setModel] = useState(state.model || 'veo-fast');
  const [aspect, setAspect] = useState(state.aspect || '16:9');
  const [duration, setDuration] = useState(state.duration || 4);
  const busy = state.status === 'running';
  const otherBusy = studioStore.anyRunning() && !busy;

  const run = async () => {
    if (studioStore.anyRunning()) return;
    if (prompt.trim().length < 3) return;
    const fullPrompt = `${prompt.trim()}. Style: ${videoStyle}. Camera motion: ${motion}. Cohesive, detailed, high production value.`;
    studioStore.begin('vid', { prompt, videoStyle, motion, model, aspect, duration });
    try {
      const { data } = await api.post('/studio/video', {
        prompt: fullPrompt, model, duration, aspect_ratio: aspect,
      });
      studioStore.complete('vid', { result: data });
    } catch (e) {
      studioStore.fail('vid', detailToString(e, 'Video generation failed'));
      toast.error(detailToString(e, 'Video generation failed'));
    }
  };

  return (
    <div className="mt-6 space-y-4">
      <div className="rounded-lg border border-border bg-card p-4 space-y-3">
        <Input data-testid="studio-video-prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)}
               placeholder="A drone shot of a rainforest at dawn..." className="h-11" />
        <ChipRow label="Style" options={['cinematic', 'documentary', 'animation', 'noir', 'commercial', 'dreamlike']} value={videoStyle} onChange={setVideoStyle} />
        <ChipRow label="Camera motion" options={['still', 'medium', 'dynamic']} value={motion} onChange={setMotion} />
        <ChipRow label="Model" options={['veo-fast', 'veo-hq']} value={model} onChange={setModel} renderLabel={(v) => v === 'veo-fast' ? 'Veo Fast' : 'Veo HQ'} />
        <ChipRow label="Aspect" options={['16:9', '9:16', '1:1']} value={aspect} onChange={setAspect} />
        <ChipRow label="Duration" options={[4, 6, 8]} value={duration} onChange={setDuration} renderLabel={(v) => `${v}s`} />
        <div className="flex justify-end">
          <Button data-testid="studio-video-btn" onClick={run} disabled={busy || otherBusy || prompt.trim().length < 3}>
            {busy ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <VideoIcon className="h-4 w-4 mr-2" />}
            {busy ? 'Rendering…' : 'Generate video'}
          </Button>
        </div>
        {otherBusy && <p className="text-xs text-center text-muted-foreground">Another generation is running — finish it first.</p>}
      </div>

      {busy && (
        <div className="rounded-lg border border-dashed border-border p-8 text-center">
          <Loader2 className="h-6 w-6 animate-spin inline mr-2 text-primary" />
          <p className="mt-3 text-sm text-muted-foreground">Rendering with Google Veo. This usually takes 1&ndash;3 minutes.</p>
          <p className="mt-1 text-xs text-muted-foreground">Switch tabs or leave this page &mdash; we&apos;ll finish in the background.</p>
        </div>
      )}
      {state.status === 'done' && state.result && (
        <div className="rounded-lg border border-border bg-card p-4 space-y-3" data-testid="studio-video-result">
          <video src={state.result.url} controls className="w-full rounded-md bg-black" />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{state.result.model} · {state.result.duration}s · {state.result.aspect_ratio || state.result.size}</span>
            <a href={state.result.url} download="iema-video.mp4" target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 text-primary hover:underline"
               data-testid="studio-video-save-btn">
              <Download className="h-3.5 w-3.5" /> Save
            </a>
          </div>
        </div>
      )}
      {state.status === 'error' && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-4 text-sm text-red-400">{state.error}</div>
      )}
    </div>
  );
}

function StudioHistory({ onOpen }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/studio/history');
      setItems(data.items || []);
    } catch { /* silent */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const open = (it) => {
    if (it.kind === 'summarize') {
      studioStore.complete('sum', { text: it.prompt || '', result: it.summary_preview || '' });
      onOpen?.('summarize');
    } else if (it.kind === 'image') {
      const urls = (it.urls || (it.url ? [it.url] : [])).map((u) => ({ url: u }));
      studioStore.complete('img', { prompt: it.prompt, images: urls });
      onOpen?.('image');
    } else if (it.kind === 'video') {
      studioStore.complete('vid', {
        prompt: it.prompt,
        result: { url: it.url, model: it.model, duration: it.duration, size: it.size },
      });
      onOpen?.('video');
    }
  };

  if (loading) return <div className="mt-6 space-y-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)}</div>;
  if (items.length === 0) return <div className="mt-6 text-center text-sm text-muted-foreground">No Studio activity yet.</div>;

  return (
    <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-3">
      {items.map((it) => (
        <button key={it.id} onClick={() => open(it)} type="button"
                className="text-left rounded-lg border border-border bg-card p-4 hover:border-primary/50 transition"
                data-testid={`studio-history-item-${it.kind}`}>
          <div className="flex justify-between items-center">
            <span className="text-xs uppercase text-primary font-semibold">{it.kind}</span>
            <span className="text-xs text-muted-foreground">{String(it.created_at || '').slice(0, 16).replace('T', ' ')}</span>
          </div>
          {it.kind === 'image' && it.urls && it.urls[0] && (
            <img src={it.urls[0]} alt="" className="w-full rounded-md mt-2" />
          )}
          {it.kind === 'video' && it.url && (
            <video src={it.url} controls onClick={(e) => e.stopPropagation()} className="w-full rounded-md mt-2 bg-black" />
          )}
          {it.kind === 'summarize' && it.summary_preview && (
            <p className="text-sm text-muted-foreground mt-2 line-clamp-4">{String(it.summary_preview)}</p>
          )}
          {it.prompt && <p className="text-xs text-muted-foreground mt-2 line-clamp-2">{String(it.prompt)}</p>}
          <p className="mt-2 text-xs text-primary">Tap to reopen &rarr;</p>
        </button>
      ))}
    </div>
  );
}

function ChipRow({ label, options, value, onChange, renderLabel }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground mb-1.5">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => (
          <button type="button" key={opt} onClick={() => onChange(opt)}
            className={`px-3 py-1.5 text-xs rounded-full border capitalize transition ${value === opt ? 'border-primary text-primary bg-primary/10' : 'border-border text-muted-foreground hover:text-foreground'}`}>
            {renderLabel ? renderLabel(opt) : String(opt)}
          </button>
        ))}
      </div>
    </div>
  );
}
