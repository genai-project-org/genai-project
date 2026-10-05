import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Loader2, MessageSquare, Plug, Search, Send } from 'lucide-react';
import { toast } from 'sonner';

function fieldLabel(field) {
  return field.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function ConnectorCard({ c, connectingId, savingId, togglingId, apiKeyDrafts, setApiKeyDrafts, connect, disconnect, saveApiKey, toggleEnabled }) {
  const draft = apiKeyDrafts[c.id] || {};
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          {c.display_name}
          <div className="flex items-center gap-1.5">
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
        {c.auth_type === 'oauth2' && !c.configured && (
          <div className="text-xs text-amber-600 dark:text-amber-400">Not configured on this server yet (missing OAuth app credentials)</div>
        )}
        {c.auth_type === 'api_key' && !c.connected && (
          <div className="space-y-2">
            {c.credential_fields.map((field) => (
              <Input
                key={field}
                type="password"
                placeholder={fieldLabel(field)}
                value={draft[field] || ''}
                onChange={(e) => setApiKeyDrafts((prev) => ({ ...prev, [c.id]: { ...prev[c.id], [field]: e.target.value } }))}
              />
            ))}
          </div>
        )}
      </CardContent>
      <CardFooter>
        {c.connected ? (
          <Button variant="outline" size="sm" onClick={() => disconnect(c.id)}>Disconnect</Button>
        ) : c.auth_type === 'api_key' ? (
          <Button size="sm" disabled={savingId === c.id} onClick={() => saveApiKey(c)}>
            {savingId === c.id ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Save & Connect'}
          </Button>
        ) : (
          <Button size="sm" disabled={!c.configured || connectingId === c.id} onClick={() => connect(c.id)}>
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
  const [savingId, setSavingId] = useState(null);
  const [togglingId, setTogglingId] = useState(null);
  const [apiKeyDrafts, setApiKeyDrafts] = useState({});
  const [search, setSearch] = useState('');
  const popupRef = useRef(null);
  const popupPollRef = useRef(null);

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

  // Popup OAuth: the popup (ConnectorOAuthCallback.jsx) posts {source:'mcp-oauth', code, state, error}
  // back to this window instead of navigating anywhere, so the main app never leaves /connectors.
  useEffect(() => {
    const onMessage = async (event) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.source !== 'mcp-oauth') return;

      if (popupPollRef.current) { clearInterval(popupPollRef.current); popupPollRef.current = null; }
      popupRef.current = null;

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

  const connect = async (connectorId) => {
    setConnectingId(connectorId);
    try {
      const redirect_uri = `${window.location.origin}/connectors/oauth-callback`;
      const { data } = await api.get(`/mcp/connect/${connectorId}`, { params: { redirect_uri } });
      const popup = window.open(data.authorize_url, 'mcp-oauth', 'width=520,height=700');
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

  const saveApiKey = async (connector) => {
    const values = apiKeyDrafts[connector.id] || {};
    setSavingId(connector.id);
    try {
      await api.post(`/mcp/connections/${connector.id}/api-key`, { values });
      toast.success('Connected');
      setApiKeyDrafts((prev) => ({ ...prev, [connector.id]: {} }));
      loadConnectors();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to connect');
    } finally {
      setSavingId(null);
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
                  savingId={savingId}
                  togglingId={togglingId}
                  apiKeyDrafts={apiKeyDrafts}
                  setApiKeyDrafts={setApiKeyDrafts}
                  connect={connect}
                  disconnect={disconnect}
                  saveApiKey={saveApiKey}
                  toggleEnabled={toggleEnabled}
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
    </div>
  );
}
