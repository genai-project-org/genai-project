import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import api, { API_BASE } from '@/lib/api';
import { setWalletBalance } from '@/store/slices/uiSlice';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import {
  Send, Sparkles, MessageSquare, Trash2, Pin, PinOff, Loader2,
  Copy, Check, Search, Plus, Paperclip, X, ImageIcon, ChevronRight,
  Share2, GraduationCap, Activity, Briefcase, Megaphone, Palette, Smile, Target, Plane
} from 'lucide-react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';
import { CHAT } from '@/constants/testIds';
import { cn } from '@/lib/utils';

// Each prompt has a short `title` (shown in the list) and the full `prompt` inserted on click.
const TEMPLATE_CATEGORIES = [
  { category: 'Social', Icon: Share2, prompts: [
    { title: 'Tweet', prompt: "Write a tweet.\nTopic: Climate change.\nTone of voice: Disappointed." },
    { title: 'LinkedIn Post', prompt: "Create a LinkedIn post.\nTopic: AI race.\nTone of voice: Professional." },
    { title: 'Instagram Caption', prompt: "Write an Instagram caption.\nTopic: AI art generation.\nTone of voice: Creative." },
    { title: 'TikTok Caption', prompt: "Write a TikTok caption.\nTopic: AI video creation.\nTone of voice: Creative." },
    { title: 'Gift Suggestions', prompt: "Act as a gift recommender. Your first message should be: 'Who do you want to buy a gift for and what are their interests?'" },
    { title: 'Text to Emoji', prompt: "Act as an emoji generator. Create emojis for: 'spicy girls'." },
    { title: 'Motivate Others', prompt: "Generate unique and inspiring phrases to motivate others on social media." },
    { title: 'YouTube Video Script', prompt: "Write a super engaging YouTube script outline about Artificial General Intelligence in the creative industry." },
  ] },
  { category: 'Education', Icon: GraduationCap, prompts: [
    { title: 'English Teacher', prompt: "Act as an English teacher. Focus on pronunciation. Summarize the topic in two paragraphs. First topic: Adjective." },
    { title: 'Math Teacher', prompt: "Act as a math teacher. Solve: 346 × 569." },
    { title: 'Essay Writer', prompt: "Write a 1000-word APA-style essay.\nTopic: AI and Human Behaviors.\nResearch Question: How can artificial intelligence feed human intelligence?" },
    { title: 'Translator', prompt: "Translate the following sentence into Spanish: 'hello'." },
    { title: 'Text Corrector', prompt: "Correct and improve: 'Don't shy before other'." },
    { title: 'Explain', prompt: "Explain: Black hole." },
  ] },
  { category: 'Health & Nutrition', Icon: Activity, prompts: [
    { title: 'Dietitian', prompt: "Design a bodybuilding recipe for 2 people with approximately 500 calories per serving and a low glycemic index." },
    { title: 'Life Coach', prompt: "Act as a life coach. First message: 'How are you feeling today?, how can I help you?'" },
    { title: 'Fitness Plan', prompt: "Create a muscle-building fitness plan for someone who is currently not exercising." },
    { title: 'Meal Generator', prompt: "Prepare a vegan dinner using carrots, broccoli, corn, and soy milk." },
    { title: 'Yoga', prompt: "Describe six safe and effective yoga poses suitable for people of all ages." },
    { title: 'Better Sleep', prompt: "Ask my age and average sleep hours before giving three recommendations to improve sleep." },
    { title: 'Calorie Calculator', prompt: "Ask my age, gender, height, weight, activity level, and weight goal before calculating daily calorie needs." },
    { title: 'Health YouTube Channels', prompt: "Recommend 10 YouTube channels about health, nutrition, and sports." },
    { title: 'Training Plan', prompt: "Generate a hypertrophy training plan with 4 workouts per week and 1-hour sessions." },
  ] },
  { category: 'Business', Icon: Briefcase, prompts: [
    { title: 'Email Writer', prompt: "Generate a formal and impactful email using the details I provide." },
    { title: 'Legal Action', prompt: "Explain possible legal actions after a car accident where I was not at fault." },
    { title: 'Blog Ideas', prompt: "Generate blog post ideas about real estate." },
    { title: 'Mock Interview', prompt: "Conduct a job interview for an Office Clerk position, asking one question at a time." },
    { title: 'Advertiser', prompt: "Write an advertisement for the iPhone 14." },
    { title: 'Job Description', prompt: "Write a Marketing Head job description requiring at least 8 years of experience." },
  ] },
  { category: 'Marketing', Icon: Megaphone, prompts: [
    { title: 'Sell Me This Pen', prompt: "Sell me this pen creatively, concisely, and persuasively." },
    { title: 'Digital Marketing Strategy', prompt: "Explain digital marketing strategies for selling shoes in one paragraph." },
    { title: 'Social Media Manager', prompt: "Help manage an organization's Twitter account to increase brand awareness." },
    { title: 'SEO Generator', prompt: "Write a short SEO-friendly paragraph about the lifestyle of lions." },
    { title: 'Marketing Plan', prompt: "Ask about my product, then generate target audience, pain points, marketing copy, video script, and SEO keywords." },
    { title: 'Caption Generator', prompt: "Generate 10 Instagram captions about Fitness and Wellness with emojis and a profile-click CTA." },
  ] },
  { category: 'Artist', Icon: Palette, prompts: [
    { title: 'Poem', prompt: "Write a poem about love." },
    { title: 'Storyteller', prompt: "Tell a story about a non-technological person entering a high-tech world." },
    { title: 'Song Recommendations', prompt: "Recommend five Hip-Hop songs with a millionaire mood." },
    { title: 'Lyrics', prompt: "Write original romantic song lyrics inspired by the storytelling style of classic love songs." },
    { title: 'Short Movie', prompt: "Write an original short movie screenplay." },
  ] },
  { category: 'Fun', Icon: Smile, prompts: [
    { title: 'Dream Interpreter', prompt: "Interpret a dream about being chased by a giant spider." },
    { title: 'Math Joke', prompt: "Tell a joke about math." },
    { title: 'Emoji Translator', prompt: "Convert 'That's what she said.' into emojis." },
    { title: 'Space Advice', prompt: "Give spacecraft advice in the style of Elon Musk." },
    { title: 'Games', prompt: "Suggest games we can play together in chat." },
    { title: 'Role Play', prompt: "Role-play in a rainforest where you are a kind little pterosaur guiding me." },
  ] },
  { category: 'Career', Icon: Target, prompts: [
    { title: 'Password Generator', prompt: "Generate a secure password." },
    { title: 'To-Do List Creator', prompt: "Ask about my goal and knowledge level before creating a to-do list." },
    { title: 'Interview Questions', prompt: "Generate 10 interview questions for a Marketing Head." },
    { title: 'Career Counselor', prompt: "Advise someone pursuing a career in software engineering." },
    { title: 'Self-Help', prompt: "Provide advice on staying motivated during difficult times." },
    { title: 'Statistician', prompt: "Calculate how many million banknotes are in active use in the world." },
    { title: 'Financial Planning', prompt: "Provide financial planning guidance." },
    { title: 'Resume Editor', prompt: "Edit and improve my resume using the information I provide." },
  ] },
  { category: 'Travel', Icon: Plane, prompts: [
    { title: 'Travel Checklist', prompt: "Create a travel checklist for Iceland in August." },
    { title: 'Places to Visit', prompt: "Recommend beach destinations in America." },
    { title: 'Best Time to Visit', prompt: "When is the best time to visit Iceland?" },
    { title: 'France Activities', prompt: "Create a travel guide for France with must-see activities." },
    { title: 'Alaska Food Trip', prompt: "Plan a 3-day Alaska trip focused on croissants and local foods." },
    { title: 'Budget Travel', prompt: "Create a France travel guide with budgeting tips." },
    { title: 'Vacation Planner', prompt: "Plan a low-budget 3-day summer trip to Sydney focused on local attractions and theatre." },
    { title: 'Safe Travel Advisor', prompt: "Ask where I want to visit, then explain important cultural traditions and legal considerations." },
  ] },
];

export default function Chat() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [meta, setMeta] = useState(null);
  const [search, setSearch] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [promptCat, setPromptCat] = useState(0);
  const [models, setModels] = useState([]);
  const [model, setModel] = useState(null);
  const [openTpl, setOpenTpl] = useState(null);
  const [tplOpen, setTplOpen] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const scrollRef = useRef(null);
  const dispatch = useDispatch();
  const { access_token } = useSelector((s) => s.auth);

  const loadConversations = async () => {
    try {
      const { data } = await api.get('/chat/conversations');
      setConversations(data.items);
    } catch { }
  };

  useEffect(() => { loadConversations(); }, []);

  useEffect(() => {
    api.get('/chat/models').then(({ data }) => {
      setModels(data.items);
      setModel(data.items.find((m) => m.default)?.id ?? data.items[0]?.id);
    }).catch(() => { });
  }, []);

  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setActiveId(null);
      setMessages([]);
      setSearchParams({});
    }
  }, [searchParams, setSearchParams]);

  const openConv = async (id) => {
    setActiveId(id);
    const { data } = await api.get(`/chat/conversations/${id}`);
    setMessages(data.messages);
  };

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, streamText]);

  const handleSend = async () => {
    const text = input.trim();
    if ((!text && attachments.length === 0) || streaming) return;
    if (!text) { toast.error('Please add a message with your image'); return; }

    setInput('');
    setStreaming(true);
    setStreamText('');
    setMeta(null);
    const sentAttachments = [...attachments];
    setAttachments([]);
    // Optimistically add user message
    const tempUserMsg = { id: 'tmp-' + Date.now(), role: 'user', content: text, attachments: sentAttachments };
    setMessages((m) => [...m, tempUserMsg]);

    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${access_token}`,
        },
        body: JSON.stringify({ content: text, conversation_id: activeId, attachments: sentAttachments, model }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Chat failed');
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalText = '';
      let convId = activeId;
      let finalMeta = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';
        for (const evt of events) {
          if (!evt.startsWith('data:')) continue;
          const payload = evt.replace(/^data:\s*/, '').trim();
          if (payload === '[DONE]') continue;
          try {
            const obj = JSON.parse(payload);
            if (obj.type === 'conversation') {
              convId = obj.conversation_id;
              if (!activeId) setActiveId(convId);
            } else if (obj.type === 'meta') {
              finalMeta = obj;
              setMeta(obj);
            } else if (obj.type === 'delta') {
              finalText += obj.content;
              setStreamText(finalText);
            } else if (obj.type === 'error') {
              toast.error(obj.message);
            } else if (obj.type === 'warn') {
              toast.info(obj.message);
            } else if (obj.type === 'saved') {
              // Refresh wallet
              api.get('/wallet/').then((r) => dispatch(setWalletBalance(r.data.total)));
            }
          } catch { }
        }
      }
      // Commit assistant message
      if (finalText) {
        setMessages((m) => [...m, {
          id: 'asst-' + Date.now(), role: 'assistant', content: finalText,
          provider: finalMeta?.provider, model: finalMeta?.model,
        }]);
      }
      setStreamText('');
      setMeta(null);
      // Refresh conversations list
      loadConversations();
    } catch (err) {
      toast.error(err.message || 'Failed to send');
    } finally {
      setStreaming(false);
    }
  };

  const deleteConv = async (id) => {
    await api.delete(`/chat/conversations/${id}`);
    if (activeId === id) { setActiveId(null); setMessages([]); }
    loadConversations();
  };

  const togglePin = async (id) => {
    await api.post(`/chat/conversations/${id}/pin`);
    loadConversations();
  };

  const filtered = conversations.filter(c => c.title.toLowerCase().includes(search.toLowerCase()));

  const handleFilePick = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (files.length === 0) return;
    setUploading(true);
    try {
      const uploaded = [];
      for (const file of files) {
        if (!file.type.startsWith('image/')) { toast.error(`${file.name}: only images supported`); continue; }
        if (file.size > 8 * 1024 * 1024) { toast.error(`${file.name}: max 8MB`); continue; }
        const form = new FormData();
        form.append('file', file);
        const { data } = await api.post('/uploads/image', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        uploaded.push({ url: data.url, content_type: data.content_type, filename: data.filename, key: data.key });
      }
      setAttachments((a) => [...a, ...uploaded]);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Upload failed');
    } finally { setUploading(false); }
  };

  const removeAttachment = (idx) => setAttachments((a) => a.filter((_, i) => i !== idx));

  return (
    <div className="flex h-full min-h-0">
      {/* Chat history sidebar */}
      <div className="hidden lg:flex w-[260px] flex-col border-r border-border">
        <div className="p-3 border-b border-border">
          <Button className="w-full justify-start gap-2" variant="outline" onClick={() => { setActiveId(null); setMessages([]); }}>
            <Plus className="h-4 w-4" /> New chat
          </Button>
        </div>
        <div className="p-3 border-b border-border">
          <div className="relative">
            <Search className="h-3.5 w-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
            <Input placeholder="Search chats" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8 h-8 text-sm" />
          </div>
        </div>

        {/* Templates */}
        <div className="border-b border-border flex flex-col" data-testid="chat-templates">
          <button
            onClick={() => setTplOpen((v) => !v)}
            className="flex items-center gap-1 px-3 py-2 text-[11px] uppercase tracking-wider text-muted-foreground/70 font-medium hover:text-muted-foreground"
          >
            <ChevronRight className={cn('h-3 w-3 transition-transform', tplOpen && 'rotate-90')} strokeWidth={2.5} />
            <span>Suggested Prompts</span>
          </button>
          {tplOpen && (
            <div className="overflow-y-auto px-2 pb-2 max-h-[40vh]">
              {TEMPLATE_CATEGORIES.map((c, idx) => {
                const isOpen = openTpl === idx;
                return (
                  <div key={c.category}>
                    <button
                      onClick={() => setOpenTpl(isOpen ? null : idx)}
                      className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                    >
                      <c.Icon className="h-4 w-4 flex-shrink-0 text-primary/70" />
                      <span className="truncate flex-1 text-left">{c.category}</span>
                      <ChevronRight className={cn('h-3.5 w-3.5 flex-shrink-0 transition-transform', isOpen && 'rotate-90')} />
                    </button>
                    {isOpen && (
                      <div className="pb-1">
                        {c.prompts.map((p) => (
                          <button
                            key={p.title}
                            onClick={() => setInput(p.prompt)}
                            title={p.prompt}
                            className="w-full text-left rounded-md pl-8 pr-2 py-1.5 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                          >
                            {p.title}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {filtered.length === 0 && <div className="text-xs text-muted-foreground text-center py-8">No conversations yet</div>}
          {filtered.map((c) => (
            <div key={c.id} data-testid={CHAT.conversationItem}
              className={cn(
                'group flex items-center gap-2 rounded-md px-2 py-1.5 cursor-pointer text-sm mb-0.5',
                activeId === c.id ? 'bg-accent' : 'hover:bg-accent/60'
              )}
              onClick={() => openConv(c.id)}
            >
              <MessageSquare className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
              <span className="truncate flex-1">{c.title}</span>
              {c.pinned && <Pin className="h-3 w-3 text-primary" />}
              <button onClick={(e) => { e.stopPropagation(); togglePin(c.id); }} className="opacity-0 group-hover:opacity-100 hover:text-foreground text-muted-foreground p-0.5">
                {c.pinned ? <PinOff className="h-3 w-3" /> : <Pin className="h-3 w-3" />}
              </button>
              <button onClick={(e) => { e.stopPropagation(); deleteConv(c.id); }} className="opacity-0 group-hover:opacity-100 hover:text-destructive text-muted-foreground p-0.5">
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          {messages.length === 0 && !streaming && (
            <div data-testid={CHAT.emptyState} className="h-full flex flex-col items-center justify-center px-4 text-center">
              <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-6">
                <Sparkles className="h-7 w-7 text-primary" strokeWidth={1.5} />
              </div>
              <h2 className="font-display text-3xl font-medium tracking-tight">How can I help you today?</h2>
              <p className="text-muted-foreground mt-2 text-sm max-w-md">
                Pick a model below the input, then start chatting. Every message costs 1 credit.
              </p>
              <div className="mt-8 w-full max-w-2xl">
                <div className="flex flex-wrap gap-2 justify-center mb-4" data-testid="chat-prompt-categories">
                  {TEMPLATE_CATEGORIES.map((c, idx) => (
                    <button
                      key={c.category}
                      onClick={() => setPromptCat(idx)}
                      className={cn(
                        'inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-sm border transition-all',
                        promptCat === idx
                          ? 'border-primary bg-primary/10 text-foreground shadow-sm'
                          : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'
                      )}
                    >
                      <c.Icon className="h-3.5 w-3.5" />
                      {c.category}
                    </button>
                  ))}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {TEMPLATE_CATEGORIES[promptCat].prompts.map((s) => (
                    <button key={s.title} onClick={() => setInput(s.prompt)} className="text-left rounded-lg border border-border bg-card hover:border-primary/40 transition-colors px-4 py-3">
                      <div className="text-sm font-medium">{s.title}</div>
                      <div className="text-xs text-muted-foreground mt-1 line-clamp-2 whitespace-pre-line">{s.prompt}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
            {messages.map((m) => <MessageBlock key={m.id} message={m} />)}
            {streaming && streamText && (
              <MessageBlock message={{ role: 'assistant', content: streamText, provider: meta?.provider, model: meta?.model, streaming: true }} />
            )}
            {streaming && !streamText && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                {meta ? `Streaming from ${meta.model}...` : 'Thinking...'}
              </div>
            )}
          </div>
        </div>

        {/* Input */}
        <div className="border-t border-border bg-background p-4">
          <div className="max-w-3xl mx-auto">
            {attachments.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-2">
                {attachments.map((att, idx) => (
                  <div key={idx} className="relative group inline-flex items-center gap-2 rounded-lg border border-border bg-card px-2 py-1.5 text-xs">
                    <ImageIcon className="h-3.5 w-3.5 text-primary" />
                    <span className="truncate max-w-[120px]">{att.filename}</span>
                    <button
                      onClick={() => removeAttachment(idx)}
                      className="h-4 w-4 rounded-full hover:bg-destructive/20 hover:text-destructive flex items-center justify-center"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {models.length > 0 && (
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Model:</span>
                <select
                  value={model ?? ''}
                  onChange={(e) => setModel(e.target.value)}
                  title={models.find((m) => m.id === model)?.description}
                  className="text-xs rounded-lg border border-border bg-card px-2.5 py-1.5 text-foreground focus:outline-none focus:border-primary/50 cursor-pointer"
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} — {m.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="relative rounded-xl border border-border bg-card focus-within:border-primary/50 transition-colors">
              <Textarea
                data-testid={CHAT.input}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
                }}
                placeholder="Message supercreator.ai..."
                rows={1}
                className="min-h-[52px] max-h-[200px] resize-none border-0 focus-visible:ring-0 pr-24 pl-12 py-3.5"
              />
              <input ref={fileInputRef} type="file" accept="image/*" multiple hidden onChange={handleFilePick} data-testid="chat-file-input" />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading || streaming}
                className="absolute left-2 bottom-2.5 h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                data-testid="chat-attach-btn"
                title="Attach image"
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
              </button>
              <Button
                data-testid={CHAT.sendBtn}
                onClick={handleSend}
                disabled={(!input.trim() && attachments.length === 0) || streaming}
                size="icon"
                className="absolute right-2 bottom-2 h-8 w-8 rounded-lg"
              >
                {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
            <div className="text-xs text-muted-foreground text-center mt-2">
              1 credit per message · +3 credits per image · Enter to send, Shift+Enter for newline
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageBlock({ message }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const isUser = message.role === 'user';
  return (
    <div data-testid={CHAT.message} className={cn('group flex gap-4 animate-fade-in-up', isUser && 'flex-row-reverse')}>
      <div className={cn(
        'h-8 w-8 rounded-md flex items-center justify-center flex-shrink-0 mt-1',
        isUser ? 'bg-primary/15 text-primary' : 'bg-foreground text-background'
      )}>
        {isUser ? <span className="text-xs font-semibold">You</span> : <Sparkles className="h-4 w-4" />}
      </div>
      <div className={cn('flex-1 min-w-0', isUser && 'flex justify-end')}>
        <div className={cn(
          isUser ? 'rounded-2xl rounded-tr-sm bg-primary/10 border border-primary/20 px-4 py-2.5 max-w-[85%]' : 'w-full'
        )}>
          {message.attachments && message.attachments.length > 0 && (
            <div className={cn('flex flex-wrap gap-2', isUser ? 'mb-2' : 'mb-3')}>
              {message.attachments.map((att, idx) => (
                <img key={idx} src={att.url} alt={att.filename} className="rounded-lg max-h-48 max-w-full border border-border" />
              ))}
            </div>
          )}
          <div className={cn('prose-chat', message.streaming && 'cursor-blink')}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {message.content}
            </ReactMarkdown>
          </div>
          {!isUser && !message.streaming && (
            <div className="flex items-center gap-3 mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={copy} className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1.5">
                {copied ? <><Check className="h-3 w-3" /> Copied</> : <><Copy className="h-3 w-3" /> Copy</>}
              </button>
              {message.model && <span className="text-xs text-muted-foreground">{message.model}</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
