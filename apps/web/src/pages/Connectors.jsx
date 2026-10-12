import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Loader2, MessageSquare, Plug, Search, Send } from 'lucide-react';
import { toast } from 'sonner';

function fieldLabel(field) {
  return field.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function ConnectorCard({ c, connectingId, togglingId, connect, disconnect, toggleEnabled, openApiKeyDialog, openDomainDialog }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          {c.display_name}
          <div className="flex items-center gap-1.5">
            {c.auth_type === 'api_key' && (
              <Badge variant="outline" className="text-muted-foreground">Requires API key</Badge>
            )}
            {c.mcp_status !== 'ready' && (
              <Badge variant="outline" className="text-muted-foreground">Actions coming soon</Badge>
            )}
            {c.connected && (
              <Switch
                checked={c.enabled}
                disabled={togglingId === c.id}
                onCheckedChange={(checked) => toggleEnabled(c.id, checked)}
                aria-label={`${c.enabled ? 'Disable' : 'Enable'} ${c.display_name}`}
              />
            )}
          </div>
        </CardTitle>
        <CardDescription>{c.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {c.external_label && <div className="text-xs text-muted-foreground">as {c.external_label}</div>}
        {c.connected && !c.enabled && (
          <div className="text-xs text-muted-foreground">Disabled — Claude won't use this until you turn it back on.</div>
        )}
        {c.auth_type === 'api_key' && !c.connected && (
          <div className="text-xs text-muted-foreground">{c.display_name} doesn't offer a login/approve flow for this — a key from their dashboard is the only option.</div>
        )}
        {(c.auth_type === 'oauth2' || c.auth_type === 'redirect_token') && !c.configured && (
          <div className="text-xs text-amber-600 dark:text-amber-400">Not configured on this server yet (missing OAuth app credentials)</div>
        )}
      </CardContent>
      <CardFooter>
        {c.connected ? (
          <Button variant="outline" size="sm" onClick={() => disconnect(c.id)}>Disconnect</Button>
        ) : c.auth_type === 'api_key' ? (
          <Button size="sm" onClick={() => openApiKeyDialog(c)}>Connect</Button>
        ) : c.requires_domain ? (
          <Button size="sm" disabled={!c.configured || connectingId === c.id} onClick={() => openDomainDialog(c)}>
            {connectingId === c.id ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Connect'}
          </Button>
        ) : (
          <Button size="sm" disabled={!c.configured || connectingId === c.id} onClick={() => connect(c)}>
            {connectingId === c.id ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Connect'}
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

  const grouped = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? connectors.filter((c) => c.display_name.toLowerCase().includes(q) || c.category.toLowerCase().includes(q))
      : connectors;
    const byCategory = {};
    for (const c of filtered) {
      (byCategory[c.category] ||= []).push(c);
    }
    return Object.entries(byCategory).sort(([a], [b]) => a.localeCompare(b));
  }, [connectors, search]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-8">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2"><Plug className="h-5 w-5" /> Connectors</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Connect your own accounts, use the switch to turn a connected service on or off, then just ask for
          things in{' '}
          <Link to="/chat" className="text-primary underline underline-offset-4 inline-flex items-center gap-1">
            AI Workspace <MessageSquare className="h-3.5 w-3.5" />
          </Link>
          {' '}— Claude will use whichever connected services it needs to get it done.
        </p>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input placeholder="Search connectors..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
      </div>

      <div className="space-y-6">
        {grouped.map(([category, items]) => (
          <div key={category} className="space-y-3">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">{category}</h2>
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
              <div className="whitespace-pre-wrap">{result.reply}</div>
              {result.tool_calls?.length > 0 && (
                <div className="border-t pt-3 space-y-1">
                  <div className="text-xs text-muted-foreground">Actions taken:</div>
                  {result.tool_calls.map((tc, i) => (
                    <div key={i} className="text-xs text-muted-foreground">
                      {tc.success ? '✓' : '✗'} {tc.connector_id}.{tc.tool_name}
                    </div>
                  ))}
                </div>
              )}
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
