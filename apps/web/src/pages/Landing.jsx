import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  Sparkles, ArrowRight, ArrowUpRight,
  Briefcase, Rocket, FlaskConical, GraduationCap, FileText, MessagesSquare, Heart,
  Award, MapPin, Wrench, Layers
} from 'lucide-react';
import ThemeToggle from '@/components/ThemeToggle';
import { HOME } from '@/constants/testIds';
import TemplateGallery from '@/components/TemplateGallery';
import { usePricing, fmtUsd, fmtInr, fmtCredits } from '@/lib/pricing';

const MODULES = [
  {
    Icon: Sparkles, name: 'AI Workspace', slug: 'workspace',
    tagline: 'One chat. Every model.',
    body: 'Talk to Claude & GPT together. Streaming answers, files, images, code — all in one gorgeous canvas.',
    live: true,
  },
  {
    Icon: Briefcase, name: 'Career Intelligence', slug: 'career',
    tagline: 'Your career, mapped.',
    body: 'Curated jobs, skill roadmaps, salary insights and interview Q&A tailored to who you are and where you want to go.',
  },
  {
    Icon: Rocket, name: 'Startup Intelligence', slug: 'startup',
    tagline: 'Ideas to ARR, faster.',
    body: 'Founder playbooks, investor signals, market maps and competitor teardowns to sharpen every decision.',
  },
  {
    Icon: FlaskConical, name: 'Research Intelligence', slug: 'research',
    tagline: 'Papers you can actually use.',
    body: 'Instant paper summaries, citation graphs, topic threads and insight extraction across millions of sources.',
  },
  {
    Icon: GraduationCap, name: 'Dynamic Course Engine', slug: 'courses',
    tagline: 'Any subject. Your syllabus.',
    body: 'Type a topic — get a full course with concepts, modules, quizzes and lessons generated for you.',
  },
  {
    Icon: FileText, name: 'Resume Intelligence', slug: 'resume',
    tagline: 'Beat the ATS. Land the call.',
    body: 'Parsing, skill matching, ATS scoring and improvement tips — with every rewrite backed by real hiring data.',
    live: true,
  },
  {
    Icon: MessagesSquare, name: 'Mock Interviews', slug: 'interviews',
    tagline: 'Practice with the interviewer that doesn\'t sleep.',
    body: 'Role-specific questions, company patterns, live feedback and a virtual interviewer that actually listens.',
  },
  {
    Icon: Heart, name: 'Counselling', slug: 'counselling',
    tagline: 'Career + Psychological support.',
    body: 'Personalised guidance, structured exercises and mood journaling — an ally on tough days and big decisions.',
  },
  {
    Icon: Award, name: 'Scholarships', slug: 'scholarships',
    tagline: 'Money you\'re eligible for.',
    body: 'Deadlines, eligibility, amounts and country filters — never miss a scholarship built for you.',
  },
  {
    Icon: MapPin, name: 'Internships', slug: 'internships',
    tagline: 'The right first step.',
    body: 'Curated internships from companies actually hiring, with role fit scoring and locations tuned to your life.',
  },
  {
    Icon: Wrench, name: 'Freelance Intelligence', slug: 'freelance',
    tagline: 'Ship projects, not proposals.',
    body: 'Live projects, skills-in-demand, rate benchmarks and platform trends — freelancing, quantified.',
  },
  {
    Icon: Layers, name: 'More Modules Coming', slug: 'more',
    tagline: 'Plug-in intelligence.',
    body: 'supercreater.ai is a growing platform. New intelligence modules ship every month. Your credits work across all of them.',
  },
];

export default function Landing() {
  const { pricing } = usePricing();
  const welcome = pricing ? fmtCredits(pricing.welcome_credits) : null;
  const daily = pricing ? fmtCredits(pricing.daily_credits) : null;

  return (
    <div className="min-h-screen bg-background text-foreground overflow-x-hidden">
      {/* Top nav */}
      <header className="glass sticky top-0 z-40">
        <div className="max-w-7xl mx-auto flex items-center justify-between px-4 sm:px-6 lg:px-8 h-14">
          <Link to="/" className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="font-display font-semibold tracking-tight">supercreater<span className="text-primary">.</span>ai</span>
          </Link>
          <nav className="hidden md:flex items-center gap-6 text-sm text-muted-foreground">
            <a href="#modules" className="hover:text-foreground">Modules</a>
            <a href="#templates" className="hover:text-foreground">Templates</a>
            <a href="#pricing" className="hover:text-foreground">Pricing</a>
            <a href="#access" className="hover:text-foreground">Access</a>
          </nav>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Link to="/login"><Button variant="ghost" size="sm">Sign in</Button></Link>
            <Link to="/register"><Button size="sm" data-testid={HOME.getStartedBtn}>Get started</Button></Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative pt-20 pb-20 sm:pt-28 sm:pb-32">
        <div className="grid-pattern absolute inset-0 pointer-events-none" />
        <div className="spot-glow" />
        <div className="relative max-w-5xl mx-auto px-4 text-center animate-fade-in-up">
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-background/60 backdrop-blur px-3 py-1 text-xs text-muted-foreground mb-6">
            <span className="h-1.5 w-1.5 rounded-full bg-primary dot-pulse" />
            Now live — v2.0 with 12 intelligence modules
          </div>
          <h1 className="font-display text-4xl sm:text-6xl lg:text-7xl font-medium tracking-tighter leading-[1.05]">
            One AI to <span className="text-primary">learn</span>,<br />
            build a career, and grow.
          </h1>
          <p className="mt-6 text-base sm:text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            supercreater.ai is a super platform for students, professionals and founders — chat, career, research,
            resume, interviews and more, all powered by top LLMs and unified by one credit wallet.
          </p>
          <div className="mt-10 flex items-center justify-center gap-3 flex-wrap">
            <Link to="/register">
              <Button size="lg" className="rounded-full px-6">
                {welcome ? `Start free \u00b7 ${welcome} credits` : 'Start free'} <ArrowRight className="h-4 w-4 ml-1" />
              </Button>
            </Link>
            <a href="#modules">
              <Button size="lg" variant="outline" className="rounded-full px-6">Explore modules</Button>
            </a>
          </div>
          <div className="mt-14 flex items-center justify-center gap-6 text-xs text-muted-foreground flex-wrap">
            <span>No card required</span>
            <span className="opacity-30">•</span>
            {daily && <span>{daily} free credits daily</span>}
            <span className="opacity-30">•</span>
            <span>Web + iOS + Android</span>
          </div>
        </div>
      </section>

      {/* Modules */}
      <section id="modules" className="py-24 border-t border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="max-w-2xl mb-14">
            <div className="text-xs uppercase tracking-wider text-primary mb-3">Intelligence Modules</div>
            <h2 className="font-display text-3xl sm:text-5xl font-medium tracking-tight leading-[1.1]">
              12 assistants.<br />One workspace.
            </h2>
            <p className="mt-4 text-muted-foreground max-w-lg">
              Every module is purpose-built for one thing — and shares your credits, history and preferences.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {MODULES.map(({ Icon, name, tagline, body, live }) => (
              <div key={name} className="group relative rounded-xl border border-border bg-card p-6 hover:border-primary/40 transition-colors flex flex-col">
                <div className="flex items-center justify-between mb-4">
                  <Icon className="h-5 w-5 text-primary" strokeWidth={1.75} />
                  {live ? (
                    <span className="text-[10px] uppercase tracking-wider bg-primary/15 text-primary px-2 py-0.5 rounded-full">Live</span>
                  ) : (
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">Coming</span>
                  )}
                </div>
                <div className="text-sm text-primary mb-1.5">{tagline}</div>
                <h3 className="font-display text-lg font-medium mb-2">{name}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed flex-1">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Access */}
      <TemplateGallery />
      <section id="access" className="py-24 border-t border-border bg-[hsl(var(--surface))]">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <div className="text-xs uppercase tracking-wider text-primary mb-3">Access anywhere</div>
            <h2 className="font-display text-3xl sm:text-4xl font-medium tracking-tight">Sign in the way you want.</h2>
            <p className="mt-3 text-muted-foreground">Google, Apple, Microsoft or Email — the same account across web, Android and iOS with multi-device sync.</p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-2xl mx-auto">
            {['Google', 'Apple', 'Microsoft', 'Email / Password'].map((p) => (
              <div key={p} className="rounded-lg border border-border bg-card p-4 text-center text-sm">{p}</div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing: rendered entirely from GET /api/pricing (single source of truth) */}
      <section id="pricing" className="py-24 border-t border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <div className="text-xs uppercase tracking-wider text-primary mb-3">Simple pricing</div>
            <h2 className="font-display text-3xl sm:text-4xl font-medium tracking-tight">One wallet. Every module.</h2>
            {pricing && (
              <p className="mt-3 text-muted-foreground">
                {welcome} free credits to start + {daily} every day. Recharge only when you need more. No subscriptions.
              </p>
            )}
          </div>
          {pricing && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-5xl mx-auto">
              <div className="rounded-2xl border border-border bg-card p-6" data-testid="landing-payg">
                <div className="text-xs uppercase tracking-wider text-primary">Pay as you go</div>
                <div className="font-display text-2xl font-medium mt-1">Recharge any amount</div>
                <p className="text-sm text-muted-foreground mt-1">
                  From {fmtUsd(pricing.payg.min_usd)} &middot; {fmtCredits(pricing.payg.credits_per_usd)} credits per $1
                </p>
                <div className="mt-4 space-y-2">
                  {pricing.payg.presets.map((x) => (
                    <div key={x.usd} className="flex items-baseline justify-between text-sm">
                      <span className="font-medium">{fmtUsd(x.usd)} <span className="text-muted-foreground">({fmtInr(x.inr)})</span></span>
                      <span className="text-muted-foreground">{fmtCredits(x.credits)} credits</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-2xl border border-border bg-card p-6" data-testid="landing-packs">
                <div className="text-xs uppercase tracking-wider text-primary">Credit packs</div>
                <div className="font-display text-2xl font-medium mt-1">Better value bundles</div>
                <div className="mt-4 space-y-2">
                  {pricing.packs.filter((x) => x.kind !== 'specialised').map((x) => (
                    <div key={x.slug} className="flex items-baseline justify-between text-sm">
                      <span className="font-medium">{x.name} <span className="text-muted-foreground">{fmtUsd(x.price_usd)}</span>
                        {x.is_popular && <span className="ml-2 text-[10px] uppercase tracking-wider bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full">Popular</span>}
                      </span>
                      <span className="text-muted-foreground">{fmtCredits(x.total_credits)} credits</span>
                    </div>
                  ))}
                </div>
                {pricing.packs.some((x) => x.kind === 'specialised') && (
                  <p className="text-xs text-muted-foreground mt-4">
                    Plus specialised packs for {pricing.packs.filter((x) => x.kind === 'specialised').map((x) => x.name.replace(' Pack', '')).join(', ')}.
                  </p>
                )}
              </div>
            </div>
          )}
          <div className="text-center mt-10">
            <Link to="/register"><Button size="lg" className="rounded-full">{welcome ? `Start free with ${welcome} credits` : 'Start free'} <ArrowUpRight className="h-4 w-4 ml-1" /></Button></Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Sparkles className="h-4 w-4 text-primary" />
            <span>supercreater.ai © 2026 — Own the data. Grow every day.</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-muted-foreground">
            <Link to="/privacy" className="hover:text-foreground">Privacy</Link>
            <a href="#" className="hover:text-foreground">Terms</a>
            <a href="#" className="hover:text-foreground">Contact</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
