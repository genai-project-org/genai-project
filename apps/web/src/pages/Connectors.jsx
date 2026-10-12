import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Info, Loader2, MessageSquare, Plug, Search, Send } from 'lucide-react';
import WorkspaceTimeline from '@/components/WorkspaceTimeline';
import { logoFor, isDarkHex } from '@/lib/connectorLogos';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

function fieldLabel(field) {
  return field.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const AVATAR_COLORS = ['bg-blue-500/15 text-blue-600', 'bg-violet-500/15 text-violet-600', 'bg-emerald-500/15 text-emerald-600',
  'bg-amber-500/15 text-amber-600', 'bg-rose-500/15 text-rose-600', 'bg-cyan-500/15 text-cyan-600', 'bg-fuchsia-500/15 text-fuchsia-600'];

function avatarClass(name) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 997;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

// A connector can be switched on unless it needs a server-wide OAuth app that isn't configured yet.
// (API-key connectors report configured=true: each user pastes their own key.)
const isAvailable = (c) => c.auth_type === 'api_key' || c.configured;

function BrandLogo({ connector }) {
  const logo = logoFor(connector.id);
  const [failed, setFailed] = useState(false);
  const showInitial = !logo || failed;
  return (
    <span
      className={cn('relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg',
        showInitial ? cn('text-sm font-semibold', avatarClass(connector.display_name)) : 'bg-muted/70')}
      aria-hidden="true"
    >
      {showInitial ? connector.display_name.charAt(0).toUpperCase() : (
        <>
          <span
            className={cn('block h-[18px] w-[18px]', logo && isDarkHex(logo.hex) && 'bg-foreground')}
            style={{
              ...(logo && !isDarkHex(logo.hex) ? { backgroundColor: `#${logo.hex}` } : {}),
              WebkitMask: `url(${logo.url}) center / contain no-repeat`,
              mask: `url(${logo.url}) center / contain no-repeat`,
            }}
          />
          {/* Probe image: lets us fall back to the initial if the icon can't be loaded. */}
          <img src={logo.url} alt="" className="absolute h-0 w-0 opacity-0" onError={() => setFailed(true)} />
        </>
      )}
    </span>
  );
}

function ConnectorRow({ c, connecting, toggling, onSwitch }) {
  const available = isAvailable(c);
  const paused = c.connected && !c.enabled;
  const on = c.connected && c.enabled;
  const busy = connecting || toggling;
  const statusLabel = c.connected ? (paused ? 'Paused' : 'Connected') : 'Not connected';
  const switchId = `connector-switch-${c.id}`;

  const toggle = (
    <Switch
      id={switchId}
      checked={on}
      disabled={!available || busy}
      className={!available ? 'disabled:opacity-70' : undefined}
      onCheckedChange={(checked) => onSwitch(c, checked)}
      aria-label={`${on ? 'Disconnect' : 'Connect'} ${c.display_name}`}
    />
  );

  return (
    <li
      className="flex min-h-[3rem] items-center gap-3 px-3 py-1.5 transition-colors hover:bg-muted/40 focus-within:bg-muted/40"
      data-testid="connector-row"
      data-connector={c.id}
      data-status={c.connected ? 'connected' : 'not-connected'}
    >
      <BrandLogo connector={c} />
      <label htmlFor={switchId} className={cn('min-w-0 flex-1 truncate text-sm font-medium', available ? 'cursor-pointer' : 'cursor-default')}>
        {c.display_name}
      </label>
      <span className="inline-flex flex-shrink-0 items-center gap-1.5 text-xs text-muted-foreground" data-testid="connector-status">
        <span
          className={cn('h-2 w-2 rounded-full', on ? 'bg-emerald-500' : paused ? 'bg-amber-500' : 'bg-muted-foreground/40')}
          aria-hidden="true"
        />
        <span className={cn('sr-only sm:not-sr-only', on && 'text-foreground')}>{statusLabel}</span>
      </span>
      <span className="flex w-[3.75rem] flex-shrink-0 items-center justify-end gap-1.5">
        {connecting && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-label="Connecting" />}
        {available ? toggle : (
          <Tooltip>
            <TooltipTrigger asChild>
              {/* Disabled controls swallow hover/focus, so the trigger is a focusable wrapper. */}
              <span tabIndex={0} className="inline-flex rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`${c.display_name}: Coming soon`}>
                {toggle}
              </span>
            </TooltipTrigger>
            <TooltipContent>Coming soon</TooltipContent>
          </Tooltip>
        )}
      </span>
    </li>
  );
}

export default function Connectors() {
  const [loading, setLoading] = useState(true);
  const [connectors, setConnectors] = useState([]);
  const [connectingId, setConnectingId] = useState(null);
  const [togglingId, setTogglingId] = useState(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all'); // all | connected
  const [category, setCategory] = useState('All');
  const [searchParams, setSearchParams] = useSearchParams();
  const autoConnectDone = useRef(false);
  const popupRef = useRef(null);
  const popupPollRef = useRef(null);

  // Switching an API-key connector on opens this dialog for the key(s) to paste.
  const [apiKeyDialogConnector, setApiKeyDialogConnector] = useState(null);
  const [apiKeyDraft, setApiKeyDraft] = useState({});
  const [savingApiKey, setSavingApiKey] = useState(false);

  // Shopify/Zendesk-style connectors: ask for the store/subdomain before opening the OAuth popup.
  const [domainDialogConnector, setDomainDialogConnector] = useState(null);
  const [domainDraft, setDomainDraft] = useState('');

  // Switching a connected connector off asks first.
  const [disconnectTarget, setDisconnectTarget] = useState(null);

  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const loadConnectors = async () => {
    try {
      const { data } = await api.get('/mcp/connectors');
      setConnectors(data || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to load connectors');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConnectors();
  }, []);

  // Popup OAuth: the popup (ConnectorOAuthCallback.jsx) posts the result back to this window
  // instead of navigating, so the app never leaves /connectors. Two message shapes: standard
  // OAuth2 code/state exchange, or a Trello-style redirect_token that's already final.
  useEffect(() => {
    const onMessage = async (event) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || (data.source !== 'mcp-oauth' && data.source !== 'mcp-oauth-token')) return;

      if (popupPollRef.current) { clearInterval(popupPollRef.current); popupPollRef.current = null; }
      popupRef.current = null;

      if (data.source === 'mcp-oauth-token') {
        try {
          await api.post(`/mcp/connections/${data.connectorId}/redirect-token`, { token: data.token });
          toast.success('Connected');
        } catch (e) {
          toast.error(e.response?.data?.detail || 'Connection failed');
        } finally {
          setConnectingId(null);
          loadConnectors();
        }
        return;
      }

      if (data.error) {
        toast.error(`Connection failed: ${data.error}`);
        setConnectingId(null);
        return;
      }
      const connectorId = (data.state || '').split('::')[0];
      try {
        const redirect_uri = `${window.location.origin}/connectors/oauth-callback`;
        await api.post(`/mcp/callback/${connectorId}`, { code: data.code, state: data.state, redirect_uri });
        toast.success('Connected');
      } catch (e) {
        toast.error(e.response?.data?.detail || 'Connection failed');
      } finally {
        setConnectingId(null);
        loadConnectors();
      }
    };
    window.addEventListener('message', onMessage);
    return () => {
      window.removeEventListener('message', onMessage);
      if (popupPollRef.current) clearInterval(popupPollRef.current);
    };
  }, []);

  const openPopupAndWait = (connectorId, authorizeUrl) => {
    const popup = window.open(authorizeUrl, 'mcp-oauth', 'width=520,height=700');
    if (!popup) {
      toast.error('Pop-up blocked — please allow pop-ups for this site and try again.');
      setConnectingId(null);
      return;
    }
    popupRef.current = popup;
    // If the user closes the popup manually without finishing, don't leave the spinner stuck.
    popupPollRef.current = setInterval(() => {
      if (popup.closed) {
        clearInterval(popupPollRef.current);
        popupPollRef.current = null;
        setConnectingId((cur) => (cur === connectorId ? null : cur));
      }
    }, 500);
  };

  const connect = async (connector, domain) => {
    const connectorId = connector.id;
    setConnectingId(connectorId);
    try {
      // The redirect URI is always this page's own origin, so the same build works on localhost
      // and in production (both are registered at the providers). Trello-style connectors have no
      // exact-match registration, so they get a ?connector= tag to route the callback.
      const base = `${window.location.origin}/connectors/oauth-callback`;
      const redirect_uri = connector.auth_type === 'redirect_token' ? `${base}?connector=${connectorId}` : base;
      const { data } = await api.get(`/mcp/connect/${connectorId}`, { params: { redirect_uri, domain } });
      openPopupAndWait(connectorId, data.authorize_url);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to start connection');
      setConnectingId(null);
    }
  };

  const disconnect = async (connectorId) => {
    try {
      await api.delete(`/mcp/connections/${connectorId}`);
      toast.success('Disconnected');
      loadConnectors();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to disconnect');
    }
  };

  const toggleEnabled = async (connectorId, enabled) => {
    setTogglingId(connectorId);
    setConnectors((prev) => prev.map((c) => (c.id === connectorId ? { ...c, enabled } : c)));
    try {
      await api.patch(`/mcp/connections/${connectorId}/toggle`, { enabled });
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to update');
      setConnectors((prev) => prev.map((c) => (c.id === connectorId ? { ...c, enabled: !enabled } : c)));
    } finally {
      setTogglingId(null);
    }
  };

  const openApiKeyDialog = (connector) => {
    setApiKeyDraft({});
    setApiKeyDialogConnector(connector);
  };

  const openDomainDialog = (connector) => {
    setDomainDraft('');
    setDomainDialogConnector(connector);
  };

  // The single entry point for every row's switch.
  const onSwitch = (c, checked) => {
    if (!checked) {
      if (c.connected) setDisconnectTarget(c);
      return;
    }
    if (c.connected) return toggleEnabled(c.id, true); // paused -> active again
    if (c.auth_type === 'api_key') return openApiKeyDialog(c);
    if (c.requires_domain) return openDomainDialog(c);
    return connect(c);
  };

  const submitDomainDialog = () => {
    if (!domainDraft.trim() || !domainDialogConnector) return;
    const connector = domainDialogConnector;
    const domain = domainDraft.trim();
    setDomainDialogConnector(null);
    connect(connector, domain);
  };

  const submitApiKeyDialog = async () => {
    if (!apiKeyDialogConnector) return;
    setSavingApiKey(true);
    try {
      await api.post(`/mcp/connections/${apiKeyDialogConnector.id}/api-key`, { values: apiKeyDraft });
      toast.success('Connected');
      setApiKeyDialogConnector(null);
      loadConnectors();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to connect');
    } finally {
      setSavingApiKey(false);
    }
  };

  const runPrompt = async () => {
    if (!prompt.trim()) return;
    setRunning(true);
    setResult(null);
    try {
      const { data } = await api.post('/mcp/prompt', { prompt });
      setResult(data);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to run prompt');
    } finally {
      setRunning(false);
    }
  };

  // Deep link from the Workspace timeline ("Connect GitHub"): /connectors?connect=github.
  // API-key connectors open their dialog straight away; OAuth ones are filtered to the row so
  // the user's own click opens the popup (browsers block popups without a click).
  useEffect(() => {
    const id = searchParams.get('connect');
    if (!id || autoConnectDone.current || loading) return;
    const c = connectors.find((x) => x.id === id);
    if (!c) return;
    autoConnectDone.current = true;
    setSearchParams({}, { replace: true });
    if (c.connected) { toast.info(`${c.display_name} is already connected`); return; }
    setSearch(c.display_name);
    if (!isAvailable(c)) { toast.info(`${c.display_name} is coming soon`); return; }
    if (c.auth_type === 'api_key') openApiKeyDialog(c);
    else toast.info(`Switch on ${c.display_name} to continue`);
  }, [connectors, loading]);

  const categories = useMemo(() => ['All', ...[...new Set(connectors.map((c) => c.category))].sort()], [connectors]);
  const connectedCount = connectors.filter((c) => c.connected && c.enabled).length;

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = connectors.filter((c) => {
      if (q && !(c.display_name.toLowerCase().includes(q) || c.category.toLowerCase().includes(q))) return false;
      if (category !== 'All' && c.category !== category) return false;
      if (filter === 'connected') return c.connected;
      return true;
    });
    const rank = (c) => (c.connected ? 0 : isAvailable(c) ? 1 : 2);
    const byCategory = {};
    for (const c of filtered) (byCategory[c.category] ||= []).push(c);
    for (const list of Object.values(byCategory)) list.sort((a, b) => rank(a) - rank(b) || a.display_name.localeCompare(b.display_name));
    return Object.entries(byCategory).sort(([a], [b]) => a.localeCompare(b));
  }, [connectors, search, filter, category]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <TooltipProvider delayDuration={150}>
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold"><Plug className="h-5 w-5" /> Connectors</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Switch on the apps you use, then ask in{' '}
              <Link to="/chat" className="inline-flex items-center gap-1 text-primary underline underline-offset-4">
                AI Workspace <MessageSquare className="h-3.5 w-3.5" />
              </Link>.
            </p>
          </div>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            <span className="font-semibold text-foreground">{connectedCount}</span> connected · {connectors.length} total
          </p>
        </div>

        <div className="space-y-2.5">
          <div className="flex items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <Input
                placeholder="Search connectors"
                aria-label="Search connectors"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-9 pl-8"
              />
            </div>
            <div className="inline-flex flex-shrink-0 rounded-lg border border-border p-0.5 text-sm" role="group" aria-label="Filter">
              {[['all', 'All'], ['connected', 'Connected']].map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={filter === v}
                  onClick={() => setFilter(v)}
                  className={cn('rounded-md px-3 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    filter === v ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:text-foreground')}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0" role="group" aria-label="Category">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                aria-pressed={category === cat}
                onClick={() => setCategory(cat)}
                className={cn('flex-shrink-0 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  category === cat ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:border-primary/40')}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {grouped.length === 0 && (
          <div className="rounded-lg border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
            No connectors match.{' '}
            <button type="button" className="text-primary underline underline-offset-4" onClick={() => { setSearch(''); setFilter('all'); setCategory('All'); }}>Clear filters</button>
          </div>
        )}

        <div className="space-y-4">
          {grouped.map(([cat, items]) => (
            <section key={cat} aria-labelledby={`cat-${cat}`}>
              <h2 id={`cat-${cat}`} className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                {cat} <span className="font-normal normal-case tracking-normal">· {items.length}</span>
              </h2>
              <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
                {items.map((c) => (
                  <ConnectorRow
                    key={c.id}
                    c={c}
                    connecting={connectingId === c.id}
                    toggling={togglingId === c.id}
                    onSwitch={onSwitch}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>

        <details className="group rounded-lg border border-border">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground">
            Quick test
          </summary>
          <div className="space-y-3 border-t border-border p-3">
            <p className="text-xs text-muted-foreground">Run one prompt against your connected apps directly. For everyday use, ask in AI Workspace.</p>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. What's on my calendar tomorrow?"
              rows={3}
            />
            <Button size="sm" onClick={runPrompt} disabled={running || !prompt.trim()}>
              {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
              Send
            </Button>
            {result && (
              <div className="space-y-3 text-sm">
                <WorkspaceTimeline plan={result.plan} steps={result.steps} />
                <div className="whitespace-pre-wrap">{result.reply}</div>
              </div>
            )}
          </div>
        </details>

        <Dialog open={!!apiKeyDialogConnector} onOpenChange={(open) => !open && setApiKeyDialogConnector(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Connect {apiKeyDialogConnector?.display_name}</DialogTitle>
              <DialogDescription>
                Paste the value{apiKeyDialogConnector?.credential_fields?.length > 1 ? 's' : ''} you got from{' '}
                {apiKeyDialogConnector?.display_name}'s own dashboard. This is stored encrypted and only used on your behalf.
              </DialogDescription>
            </DialogHeader>
            {apiKeyDialogConnector?.notes && (
              <div className="flex gap-2 rounded-md bg-muted/60 p-2.5 text-xs text-muted-foreground">
                <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" /> {apiKeyDialogConnector.notes}
              </div>
            )}
            <form
              className="space-y-3"
              onSubmit={(e) => { e.preventDefault(); submitApiKeyDialog(); }}
            >
              {apiKeyDialogConnector?.credential_fields.map((field) => (
                <div key={field} className="space-y-1.5">
                  <label htmlFor={`cred-${field}`} className="text-sm font-medium">{fieldLabel(field)}</label>
                  <Input
                    id={`cred-${field}`}
                    type="password"
                    autoComplete="off"
                    value={apiKeyDraft[field] || ''}
                    onChange={(e) => setApiKeyDraft((prev) => ({ ...prev, [field]: e.target.value }))}
                  />
                </div>
              ))}
              <DialogFooter>
                <Button type="submit" disabled={savingApiKey}>
                  {savingApiKey ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Connect
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

        <Dialog open={!!domainDialogConnector} onOpenChange={(open) => !open && setDomainDialogConnector(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Connect {domainDialogConnector?.display_name}</DialogTitle>
              <DialogDescription>
                {domainDialogConnector?.display_name} has its own login per account — enter your{' '}
                {domainDialogConnector?.domain_label?.toLowerCase()} and we'll take you straight to their login screen.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5">
              <label htmlFor="connector-domain" className="text-sm font-medium">{domainDialogConnector?.domain_label}</label>
              <Input
                id="connector-domain"
                placeholder={domainDialogConnector?.domain_placeholder}
                value={domainDraft}
                onChange={(e) => setDomainDraft(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submitDomainDialog()}
              />
            </div>
            <DialogFooter>
              <Button onClick={submitDomainDialog} disabled={!domainDraft.trim()}>Continue</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <AlertDialog open={!!disconnectTarget} onOpenChange={(open) => !open && setDisconnectTarget(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Disconnect {disconnectTarget?.display_name}?</AlertDialogTitle>
              <AlertDialogDescription>
                The assistant will lose access to {disconnectTarget?.display_name} and your saved credentials will be deleted.
                You can connect it again any time.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep connected</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => { const id = disconnectTarget.id; setDisconnectTarget(null); disconnect(id); }}
              >
                Disconnect
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </TooltipProvider>
  );
}
