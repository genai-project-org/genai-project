import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Sparkles, ExternalLink, Play, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

const API = process.env.REACT_APP_BACKEND_URL;

export default function TemplateGallery() {
  const [items, setItems] = useState([]);
  const [active, setActive] = useState(null);
  const [html, setHtml] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    axios.get(`${API}/api/builder/templates`).then(r => {
      setItems(r.data.items || []);
      if (r.data.items?.length) selectTemplate(r.data.items[0].slug);
    }).catch(() => {});
  }, []);

  const selectTemplate = async (slug) => {
    setActive(slug); setLoading(true);
    try {
      const { data } = await axios.get(`${API}/api/builder/templates/${slug}/preview`);
      setHtml(data.html);
    } finally { setLoading(false); }
  };

  if (items.length === 0) return null;

  return (
    <section id="templates" className="py-24 border-t border-border" data-testid="landing-templates">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="max-w-2xl mb-12">
          <div className="text-xs uppercase tracking-wider text-primary mb-3">Code Builder — Live Preview</div>
          <h2 className="font-display text-3xl sm:text-5xl font-medium tracking-tight leading-[1.1]">
            Ship apps in 15 credits.
          </h2>
          <p className="mt-4 text-muted-foreground max-w-lg">
            Pick a template. See it live below. Sign up and remix it into your own — or describe any app and supercreator will build it.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
          {/* Template list */}
          <div className="space-y-2 order-2 lg:order-1" data-testid="landing-template-list">
            {items.map((t) => (
              <button
                key={t.slug}
                onClick={() => selectTemplate(t.slug)}
                data-testid={`landing-template-${t.slug}`}
                className={cn(
                  'w-full text-left rounded-xl border p-4 transition-all',
                  active === t.slug
                    ? 'border-primary bg-primary/5 shadow-sm'
                    : 'border-border bg-card hover:border-primary/40'
                )}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                  <span className="text-sm font-medium">{t.name}</span>
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2">{t.description}</p>
              </button>
            ))}
            <Link to="/register" className="block mt-4">
              <Button size="lg" className="w-full rounded-full gap-2" data-testid="landing-template-cta">
                Remix these free <ExternalLink className="h-4 w-4" />
              </Button>
            </Link>
          </div>

          {/* Preview */}
          <div className="rounded-xl border border-border overflow-hidden bg-white order-1 lg:order-2 min-h-[420px]" data-testid="landing-template-preview">
            <div className="border-b border-border bg-[hsl(var(--surface))] px-4 py-2 flex items-center gap-2 text-xs">
              <div className="flex gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-red-400/70"></span>
                <span className="h-2.5 w-2.5 rounded-full bg-yellow-400/70"></span>
                <span className="h-2.5 w-2.5 rounded-full bg-green-400/70"></span>
              </div>
              <div className="ml-3 text-muted-foreground truncate flex items-center gap-1.5">
                <Play className="h-3 w-3" />
                {items.find(i => i.slug === active)?.name || 'Preview'}
              </div>
              <div className="ml-auto text-[10px] text-muted-foreground uppercase tracking-wider">Live</div>
            </div>
            {loading ? (
              <div className="flex items-center justify-center h-96 text-muted-foreground text-sm">
                <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading preview…
              </div>
            ) : (
              <iframe
                title="template-preview"
                srcDoc={html}
                sandbox="allow-scripts allow-forms"
                className="w-full h-[560px] bg-white border-0"
                data-testid="landing-template-iframe"
              />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
