import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, Plug } from 'lucide-react';

/**
 * Popup-window OAuth callback for connecting a third-party service
 * (apps/web/src/pages/Connectors.jsx) — modeled on AuthCallback.jsx's shape,
 * but this one never navigates the main app: it just hands the code/state
 * back to the window that opened it via postMessage, then closes itself.
 * Connectors.jsx's own `state` is prefixed `${connectorId}::...}` (see
 * services/mcp/oauth_service.py's build_authorize_url), so the opener can
 * tell which connector this callback belongs to without a second round trip.
 */
export default function ConnectorOAuthCallback() {
  const [params] = useSearchParams();
  const sentRef = useRef(false);
  const [closed, setClosed] = useState(false);

  useEffect(() => {
    if (sentRef.current) return;
    sentRef.current = true;

    const code = params.get('code');
    const state = params.get('state');
    const error = params.get('error') || params.get('error_description');

    window.opener?.postMessage({ source: 'mcp-oauth', code, state, error }, window.location.origin);

    const t = setTimeout(() => {
      window.close();
      setClosed(true);
    }, 400);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background">
      <div className="h-14 w-14 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center mb-6">
        <Plug className="h-6 w-6 text-primary" />
      </div>
      {!closed ? (
        <>
          <Loader2 className="h-6 w-6 animate-spin text-primary mb-2" />
          <p className="text-muted-foreground text-sm">Connecting…</p>
        </>
      ) : (
        <p className="text-muted-foreground text-sm">You can close this window.</p>
      )}
    </div>
  );
}
