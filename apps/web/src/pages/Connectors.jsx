import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Info, Loader2, MessageSquare, Plug, Search, Send, Zap } from 'lucide-react';
import WorkspaceTimeline from '@/components/WorkspaceTimeline';
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

// connected | available (can be connected) | soon (account can be linked, actions not built yet)
function statusOf(c) {
  if (c.connected) return 'connected';
  if (c.mcp_status !== 'ready') return 'soon';
  return 'available';
}

function StatusPill({ status, enabled }) {
  if (status === 'connected') {
    return (
      <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
        enabled ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' : 'bg-muted text-muted-foreground')}>
        <span className={cn('h-1.5 w-1.5 rounded-full', enabled ? 'bg-emerald-500' : 'bg-muted-foreground')} />
        {enabled ? 'Connected' : 'Paused'}
      </span>
    );
  }
  if (status === 'soon') {
    return <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">Coming soon</span>;
  }
  return <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">Available</span>;
}

function ConnectorCard({ c, connectingId, togglingId, connect, disconnect, toggleEnabled, openApiKeyDialog, openDomainDialog, openUnavailableDialog }) {
  const status = statusOf(c);
  const needsServerSetup = c.auth_type !== 'api_key' && !c.configured;
  const connecting = connectingId === c.id;
  const onConnect = () => {
    if (needsServerSetup) return openUnavailableDialog(c);
    if (c.auth_type === 'api_key') return openApiKeyDialog(c);
    if (c.requires_domain) return openDomainDialog(c);
    return connect(c);
  };
  return (
    <Card className={cn('flex flex-col transition-colors', status === 'connected' && 'border-emerald-500/30')} data-testid="connector-card" data-status={status}>
      <CardHeader className="pb-3">
        <div className="flex items-start gap-3">
          <div className={cn('flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg text-base font-semibold', avatarClass(c.display_name))}>
            {c.display_name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              <span className="truncate">{c.display_name}</span>
              <StatusPill status={status} enabled={c.enabled} />
            </CardTitle>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {c.mcp_status === 'ready' && (
                <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground"><Zap className="h-3 w-3" /> Live actions</span>
              )}
              <span className="text-[11px] text-muted-foreground">
                {c.mcp_status === 'ready' ? '· ' : ''}{c.auth_type === 'api_key' ? 'API key' : 'Sign in'}
              </span>
            </div>
          </div>
        </div>
        <CardDescription className="pt-2">{c.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex-1 space-y-1 pb-3 text-xs text-muted-foreground">
        {c.external_label && <div>Connected as {c.external_label}</div>}
        {c.connected && !c.enabled && <div>Paused — the assistant won't use it until you turn it back on.</div>}
        {!c.connected && needsServerSetup && c.mcp_status === 'ready' && (
          <div>Sign-in for this service is being switched on for the workspace.</div>
        )}
        {!c.connected && c.mcp_status !== 'ready' && <div>You'll be able to connect this and use it from the Workspace soon.</div>}
      </CardContent>
      <CardFooter className="justify-between gap-2">
        {c.connected ? (
          <>
            <Button variant="outline" size="sm" onClick={() => disconnect(c.id)}>Disconnect</Button>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              {c.enabled ? 'On' : 'Off'}
              <Switch
                checked={c.enabled}
                disabled={togglingId === c.id}
                onCheckedChange={(checked) => toggleEnabled(c.id, checked)}
                aria-label={`${c.enabled ? 'Pause' : 'Enable'} ${c.display_name}`}
              />
            </label>
          </>
        ) : status === 'soon' ? (
          <Button size="sm" variant="outline" disabled>Coming soon</Button>
        ) : (
          <Button size="sm" disabled={connecting} onClick={onConnect}>
            {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Connect'}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

export default function Connectors() {
  const [loading, setLoading] = useState(true);
  const [connectors, setConnectors] = useState([]);
  const [connectingId, setConnectingId] = useState(null);
  const [togglingId, setTogglingId] = useState(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all'); // all | connected | available
  const [category, setCategory] = useState('All');
  const [unavailableConnector, setUnavailableConnector] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const autoConnectDone = useRef(false);
  const popupRef = useRef(null);
  const popupPollRef = useRef(null);

  // The api_key "Connect" button opens this dialog instead of showing raw
  // input boxes on the card itself — keeps every card's resting state down
  // to just a Connect/Disconnect button + toggle, same as the OAuth ones.
  const [apiKeyDialogConnector, setApiKeyDialogConnector] = useState(null);
  const [apiKeyDraft, setApiKeyDraft] = useState({});
  const [savingApiKey, setSavingApiKey] = useState(false);

  // Shopify-style connectors: ask for the store domain (not a secret — just
  // which host to send the user to) before opening the OAuth popup.
  const [domainDialogConnector, setDomainDialogConnector] = useState(null);
  const [domainDraft, setDomainDraft] = useState('');

  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const loadConnectors = async () => {
    setLoading(true);
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

  // Popup OAuth: the popup (ConnectorOAuthCallback.jsx) posts the result back
  // to this window instead of navigating anywhere, so the main app never
  // leaves /connectors. Two message shapes: standard OAuth2 code/state
  // exchange, or a Trello-style redirect_token that's already final.
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
      // Trello-style connectors have no registered redirect URI to match
      // exactly, so it's safe (and necessary) to tag which connector this
      // callback is for — standard OAuth2 providers require redirect_uri to
      // match their registered value exactly, so that tag is omitted there.
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
  // API-key connectors open their dialog straight away; OAuth ones are filtered to the
  // card so the user's own click opens the popup (browsers block popups without a click).
  useEffect(() => {
    const id = searchParams.get('connect');
    if (!id || autoConnectDone.current || loading) return;
    const c = connectors.find((x) => x.id === id);
    if (!c) return;
    autoConnectDone.current = true;
    setSearchParams({}, { replace: true });
    if (c.connected) { toast.info(`${c.display_name} is already connected`); return; }
    setSearch(c.display_name);
    if (c.auth_type === 'api_key') openApiKeyDialog(c);
    else toast.info(`Click Connect on ${c.display_name} to continue`);
  }, [connectors, loading]);

  const categories = useMemo(() => ['All', ...[...new Set(connectors.map((c) => c.category))].sort()], [connectors]);
  const connectedCount = connectors.filter((c) => c.connected).length;
  const liveCount = connectors.filter((c) => c.mcp_status === 'ready').length;

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = connectors.filter((c) => {
      if (q && !(c.display_name.toLowerCase().includes(q) || c.category.toLowerCase().includes(q) || c.description.toLowerCase().includes(q))) return false;
      if (category !== 'All' && c.category !== category) return false;
      if (filter === 'connected') return c.connected;
      if (filter === 'available') return !c.connected && c.mcp_status === 'ready';
      return true;
    });
    const rank = (c) => (c.connected ? 0 : c.mcp_status === 'ready' ? 1 : 2);
    const byCategory = {};
    for (const c of filtered) {
      (byCategory[c.category] ||= []).push(c);
    }
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
    <div className="max-w-5xl mx-auto p-6 space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-semibold flex items-center gap-2"><Plug className="h-5 w-5" /> Connectors</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Connect your own accounts, then just describe a goal in{' '}
            <Link to="/chat" className="text-primary underline underline-offset-4 inline-flex items-center gap-1">
              AI Workspace <MessageSquare className="h-3.5 w-3.5" />
            </Link>
            {' '}— the assistant plans the steps and uses whichever connected services it needs.
          </p>
        </div>
        <div className="flex gap-3 text-center">
          <div className="rounded-lg border border-border px-4 py-2">
            <div className="text-xl font-semibold">{connectedCount}</div>
            <div className="text-[11px] text-muted-foreground">Connected</div>
          </div>
          <div className="rounded-lg border border-border px-4 py-2">
            <div className="text-xl font-semibold">{liveCount}</div>
            <div className="text-[11px] text-muted-foreground">With live actions</div>
          </div>
          <div className="rounded-lg border border-border px-4 py-2">
            <div className="text-xl font-semibold">{connectors.length}</div>
            <div className="text-[11px] text-muted-foreground">Total</div>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-full max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input placeholder="Search connectors..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
          </div>
          <div className="inline-flex rounded-lg border border-border p-0.5 text-sm">
            {[['all', 'All'], ['connected', 'Connected'], ['available', 'Ready to connect']].map(([v, label]) => (
              <button
                key={v}
                onClick={() => setFilter(v)}
                className={cn('rounded-md px-3 py-1', filter === v ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:text-foreground')}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={cn('rounded-full border px-3 py-1 text-xs transition-colors',
                category === cat ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:border-primary/40')}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {grouped.length === 0 && (
        <div className="rounded-xl border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
          No connectors match your filters.{' '}
          <button className="text-primary underline underline-offset-4" onClick={() => { setSearch(''); setFilter('all'); setCategory('All'); }}>Clear filters</button>
        </div>
      )}

      <div className="space-y-6">
        {grouped.map(([category, items]) => (
          <div key={category} className="space-y-3">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              {category} <span className="font-normal normal-case">· {items.length}</span>
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((c) => (
                <ConnectorCard
                  key={c.id}
                  c={c}
                  connectingId={connectingId}
                  togglingId={togglingId}
                  connect={connect}
                  disconnect={disconnect}
                  toggleEnabled={toggleEnabled}
                  openApiKeyDialog={openApiKeyDialog}
                  openDomainDialog={openDomainDialog}
                  openUnavailableDialog={setUnavailableConnector}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-medium">Quick test</h2>
        <p className="text-sm text-muted-foreground">
          For everyday use, just ask in <Link to="/chat" className="text-primary underline underline-offset-4">AI Workspace</Link> —
          this box is a quick way to test one prompt against your connected services directly.
        </p>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. What's on my calendar tomorrow?"
          rows={3}
        />
        <Button onClick={runPrompt} disabled={running || !prompt.trim()}>
          {running ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Send className="h-4 w-4 mr-2" />}
          Send
        </Button>

        {result && (
          <Card>
            <CardContent className="pt-6 space-y-3 text-sm">
              <WorkspaceTimeline plan={result.plan} steps={result.steps} />
              <div className="whitespace-pre-wrap">{result.reply}</div>
            </CardContent>
          </Card>
        )}
      </div>

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
          <div className="space-y-3">
            {apiKeyDialogConnector?.credential_fields.map((field) => (
              <div key={field} className="space-y-1.5">
                <label className="text-sm font-medium">{fieldLabel(field)}</label>
                <Input
                  type="password"
                  autoComplete="off"
                  value={apiKeyDraft[field] || ''}
                  onChange={(e) => setApiKeyDraft((prev) => ({ ...prev, [field]: e.target.value }))}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button onClick={submitApiKeyDialog} disabled={savingApiKey}>
              {savingApiKey ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              Connect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!unavailableConnector} onOpenChange={(open) => !open && setUnavailableConnector(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{unavailableConnector?.display_name} is almost ready</DialogTitle>
            <DialogDescription>
              {unavailableConnector?.display_name} is supported, but sign-in hasn't been switched on for this workspace yet.
              As soon as it is, the Connect button will work right here — nothing for you to fix.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setUnavailableConnector(null)}>Got it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!domainDialogConnector} onOpenChange={(open) => !open && setDomainDialogConnector(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Connect {domainDialogConnector?.display_name}</DialogTitle>
            <DialogDescription>
              {domainDialogConnector?.display_name} has its own OAuth login per account — enter your{' '}
              {domainDialogConnector?.domain_label?.toLowerCase()} and we'll take you straight to their login screen.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">{domainDialogConnector?.domain_label}</label>
            <Input
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
    </div>
  );
}
