import { useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import api from '@/lib/api';
import { setWalletBalance } from '@/store/slices/uiSlice';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Loader2, Heart, Briefcase, GraduationCap, Send, Volume2, Square, Clock, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const MODES = [
  { key: 'career', label: 'Career', Icon: Briefcase, hint: 'Confidential career advice. India tech context.', accent: 'from-indigo-500/20 to-indigo-500/5', hero: 'counseling-hero.png' },
  { key: 'psychology', label: 'Wellness', Icon: Heart, hint: 'Not a licensed therapist. Compassionate listening.', accent: 'from-rose-500/20 to-rose-500/5', hero: 'counseling-hero-wellness.png' },
  { key: 'academic', label: 'Academic', Icon: GraduationCap, hint: 'Study plans, exam strategies, free resources.', accent: 'from-emerald-500/20 to-emerald-500/5', hero: 'counseling-hero-academic.png' },
];

export default function Counseling() {
  const [mode, setMode] = useState('career');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [speakingIdx, setSpeakingIdx] = useState(null);
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const dispatch = useDispatch();
  const scrollRef = useRef(null);
  const pendingRestore = useRef(null);
  const activeMode = MODES.find(m => m.key === mode);

  // Load history from backend (syncs across devices) — normalize to {id, mode, q, a, ts}.
  useEffect(() => {
    api.get('/counseling/history')
      .then(({ data }) => setHistory(data.items.map(it => ({ id: it.id, mode: it.mode, q: it.question, a: it.answer, ts: it.created_at }))))
      .catch(() => {});
  }, []);

  // Reset thread when the user switches mode — unless we're restoring a history item.
  useEffect(() => {
    if (pendingRestore.current) { setMessages(pendingRestore.current); pendingRestore.current = null; }
    else setMessages([]);
  }, [mode]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }); }, [messages, loading]);
  useEffect(() => () => window.speechSynthesis?.cancel(), []);  // stop TTS on unmount

  // Pick a female English voice as the default. ponytail: name-heuristic — Web Speech
  // exposes no gender field, so we match known female voice names; falls back to any voice.
  const voiceRef = useRef(null);
  useEffect(() => {
    const synth = window.speechSynthesis;
    if (!synth) return;
    const pick = () => {
      const voices = synth.getVoices();
      if (!voices.length) return;
      const en = voices.filter(v => /^en/i.test(v.lang));
      const pool = en.length ? en : voices;
      const female = pool.find(v => /female|woman|zira|samantha|susan|karen|tessa|fiona|moira|serena|victoria|allison|joanna|salli|kendra|hazel|linda|heera|aria|jenny|sonia|neerja|google uk english female|google us english/i.test(v.name));
      voiceRef.current = female || pool[0] || null;
    };
    pick();
    synth.addEventListener('voiceschanged', pick);
    return () => synth.removeEventListener('voiceschanged', pick);
  }, []);

  const speak = (text, idx) => {
    const synth = window.speechSynthesis;
    if (!synth) return toast.error('Text-to-speech not supported in this browser');
    synth.cancel();
    if (speakingIdx === idx) return setSpeakingIdx(null);  // toggle off
    // strip markdown so it reads cleanly
    const clean = text.replace(/\[(.*?)\]\(.*?\)/g, '$1').replace(/[*_`#>]/g, '');
    const u = new SpeechSynthesisUtterance(clean);
    if (voiceRef.current) { u.voice = voiceRef.current; u.lang = voiceRef.current.lang; }
    u.onend = u.onerror = () => setSpeakingIdx(null);
    setSpeakingIdx(idx);
    synth.speak(u);
  };

  const send = async () => {
    const text = input.trim();
    if (text.length < 3) return;
    const userMsg = { role: 'user', text };
    setMessages(prev => [...prev, userMsg]); setInput(''); setLoading(true);
    try {
      const { data } = await api.post('/counseling', { mode, message: text });
      if (data.balance != null) dispatch(setWalletBalance(data.balance));
      setMessages(prev => [...prev, {
        role: 'assistant', text: data.response, source: data.source,
        score: data.score, disclaimer: data.disclaimer, credits: data.credits_used,
      }]);
      // Backend already persisted this exchange — reflect it locally (newest first).
      setHistory(prev => [{ mode, q: text, a: data.response, ts: new Date().toISOString() }, ...prev]);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Counsel failed');
    } finally { setLoading(false); }
  };

  const openHistory = (h) => {
    setShowHistory(false);
    const restored = [{ role: 'user', text: h.q }, { role: 'assistant', text: h.a }];
    if (h.mode !== mode) { pendingRestore.current = restored; setMode(h.mode); }
    else setMessages(restored);
  };

  const clearHistory = async () => {
    try { await api.delete('/counseling/history'); setHistory([]); }
    catch { toast.error('Could not clear history'); }
  };

  return (
    <div className="h-full flex flex-col" data-testid="counseling-page">
      <div className="border-b border-border p-4 md:p-6">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center gap-3 mb-4">
            <div className="h-11 w-11 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center">
              <Heart className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1">
              <h1 className="font-display text-2xl md:text-3xl font-semibold tracking-tight">Counseling</h1>
              <p className="text-sm text-muted-foreground">{activeMode.hint}</p>
            </div>
            <button
              onClick={() => setShowHistory(v => !v)}
              data-testid="counseling-history-toggle"
              className={cn(
                'inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-medium transition-all',
                showHistory
                  ? 'border-primary/40 bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'
              )}
            >
              <Clock className="h-4 w-4" />
              <span className="hidden sm:inline">History</span>
              {history.length > 0 && <span className="text-xs rounded-full bg-primary/15 text-primary px-1.5">{history.length}</span>}
            </button>
          </div>

          {showHistory && (
            <div className="mb-4 rounded-xl border border-border bg-card overflow-hidden" data-testid="counseling-history">
              <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                <span className="text-xs uppercase tracking-wider text-muted-foreground font-medium">Previous conversations</span>
                {history.length > 0 && (
                  <button onClick={clearHistory} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive transition-colors">
                    <Trash2 className="h-3.5 w-3.5" /> Clear
                  </button>
                )}
              </div>
              <div className="max-h-64 overflow-y-auto p-1">
                {history.length === 0 ? (
                  <div className="text-sm text-muted-foreground p-4 text-center">No previous conversations yet.</div>
                ) : history.map((h, i) => {
                  const hm = MODES.find(m => m.key === h.mode);
                  return (
                    <button
                      key={i}
                      onClick={() => openHistory(h)}
                      className="w-full text-left rounded-lg px-3 py-2 hover:bg-accent flex items-center gap-3 transition-colors"
                    >
                      <span className="text-[10px] uppercase tracking-wide rounded-full bg-primary/10 text-primary px-2 py-0.5 flex-shrink-0">{hm?.label || h.mode}</span>
                      <span className="text-sm truncate flex-1">{h.q}</span>
                      <span className="text-xs text-muted-foreground flex-shrink-0">{new Date(h.ts).toLocaleDateString()}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <div className="flex gap-2 flex-wrap" data-testid="counseling-mode-picker">
            {MODES.map(m => (
              <button
                key={m.key}
                onClick={() => setMode(m.key)}
                data-testid={`counseling-mode-${m.key}`}
                className={cn(
                  'flex items-center gap-2 px-4 py-2 rounded-full text-sm border transition-all',
                  mode === m.key
                    ? 'border-primary bg-primary/10 text-foreground shadow-sm'
                    : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'
                )}
              >
                <m.Icon className="h-3.5 w-3.5" />
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 md:p-6">
        <div className="max-w-3xl mx-auto space-y-4" data-testid="counseling-thread">
          {messages.length === 0 && (
            <img
              src={`${process.env.PUBLIC_URL}/${activeMode.hero}`}
              alt={`${activeMode.label} — start a private conversation`}
              className="w-full rounded-2xl border border-border"
              data-testid="counseling-empty-hero"
            />
          )}
          {messages.map((m, i) => (
            <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              <div className={cn(
                'max-w-[85%] rounded-2xl px-4 py-3',
                m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-card border border-border'
              )}>
                {m.role === 'user' ? (
                  <div className="text-sm">{m.text}</div>
                ) : (
                  <>
                    <div className="prose-chat text-sm">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                    </div>
                    <button
                      onClick={() => speak(m.text, i)}
                      className={cn(
                        'mt-3 inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-semibold text-white shadow-sm transition-all hover:shadow-md hover:brightness-110 active:scale-95',
                        speakingIdx === i
                          ? 'bg-gradient-to-r from-rose-500 to-orange-500'
                          : 'bg-gradient-to-r from-blue-600 via-blue-500 to-cyan-500'
                      )}
                      data-testid="counseling-tts-btn"
                      title={speakingIdx === i ? 'Stop' : 'Read aloud'}
                    >
                      {speakingIdx === i ? (
                        <>
                          <Square className="h-3.5 w-3.5 fill-current" />
                          <span>Stop</span>
                          <span className="flex items-end gap-0.5 h-3">
                            <span className="w-0.5 bg-white rounded-full animate-pulse" style={{ height: '60%', animationDelay: '0ms' }} />
                            <span className="w-0.5 bg-white rounded-full animate-pulse" style={{ height: '100%', animationDelay: '150ms' }} />
                            <span className="w-0.5 bg-white rounded-full animate-pulse" style={{ height: '40%', animationDelay: '300ms' }} />
                          </span>
                        </>
                      ) : (
                        <><Volume2 className="h-4 w-4" /> <span>Listen</span></>
                      )}
                    </button>
                    {m.disclaimer && (
                      <div className="mt-3 text-[11px] text-muted-foreground italic border-t border-border/50 pt-2">
                        {m.disclaimer}
                      </div>
                    )}
                    </>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start"><div className="bg-card border border-border rounded-2xl px-4 py-3 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Consulting…
            </div></div>
          )}
        </div>
      </div>

      <div className="border-t border-border p-3 md:p-4 bg-background">
        <div className="max-w-3xl mx-auto flex gap-2 items-end">
          <Textarea
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            rows={2}
            placeholder={mode === 'psychology' ? "What's on your mind? This is a safe space." :
              mode === 'academic' ? 'Ask about a subject, exam, or study plan…' :
              'Ask about your career move, skills, salary, next role…'}
            className="resize-none min-h-[52px] max-h-40"
            data-testid="counseling-input"
          />
          <Button onClick={send} disabled={loading || input.trim().length < 3} className="h-[52px] px-5" data-testid="counseling-send-btn">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}
