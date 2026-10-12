import { useState } from 'react';
import { Check, ChevronDown, ChevronRight, CircleDashed, Loader2, RotateCw, X, ListChecks } from 'lucide-react';
import api from '@/lib/api';
import { cn } from '@/lib/utils';

const STATUS_LABEL = { pending: 'Queued', running: 'Running', done: 'Done', failed: 'Failed' };

function StatusIcon({ status }) {
  const base = 'h-5 w-5 rounded-full flex items-center justify-center flex-shrink-0';
  if (status === 'running') {
    return <span className={cn(base, 'bg-primary/15 text-primary')}><Loader2 className="h-3 w-3 animate-spin" /></span>;
  }
  if (status === 'done') {
    return <span className={cn(base, 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400')}><Check className="h-3 w-3" /></span>;
  }
  if (status === 'failed') {
    return <span className={cn(base, 'bg-red-500/15 text-red-600 dark:text-red-400')}><X className="h-3 w-3" /></span>;
  }
  return <span className={cn(base, 'bg-muted text-muted-foreground')}><CircleDashed className="h-3 w-3" /></span>;
}

function formatMs(ms) {
  if (ms == null) return null;
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function Step({ step, last, onRetry, retrying }) {
  const [open, setOpen] = useState(false);
  const failed = step.status === 'failed';
  const hasDetails = step.raw || (step.args && Object.keys(step.args).length > 0) || step.error;
  return (
    <li className="relative flex gap-3" data-testid="workspace-step" data-status={step.status}>
      {!last && <span className="absolute left-[9px] top-6 bottom-[-8px] w-px bg-border" aria-hidden="true" />}
      <StatusIcon status={step.status} />
      <div className="flex-1 min-w-0 pb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium">{step.title}</span>
          <span
            className={cn(
              'text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5',
              step.status === 'done' && 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
              step.status === 'failed' && 'bg-red-500/10 text-red-700 dark:text-red-400',
              step.status === 'running' && 'bg-primary/10 text-primary',
              step.status === 'pending' && 'bg-muted text-muted-foreground',
            )}
          >
            {STATUS_LABEL[step.status] || step.status}
          </span>
          {formatMs(step.duration_ms) && <span className="text-[11px] text-muted-foreground">{formatMs(step.duration_ms)}</span>}
        </div>

        {step.args_readable?.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {step.args_readable.map((a) => (
              <span key={a.label} className="inline-flex max-w-full items-baseline gap-1 rounded-md border border-border bg-muted/40 px-1.5 py-0.5 text-[11px]">
                <span className="text-muted-foreground">{a.label}</span>
                <span className="truncate text-foreground">{a.value}</span>
              </span>
            ))}
          </div>
        )}

        {step.status === 'done' && step.summary && (
          <p className="mt-1.5 text-xs text-muted-foreground">{step.summary}</p>
        )}

        {failed && (
          <div className="mt-1.5 rounded-md border border-red-500/30 bg-red-500/5 px-2.5 py-2 text-xs">
            <p className="text-red-700 dark:text-red-300">{step.friendly_error || 'This step could not be completed.'}</p>
            {step.retryable !== false && step.tool !== 'connect' && (
              <button
                onClick={() => onRetry(step)}
                disabled={retrying}
                className="mt-1.5 inline-flex items-center gap-1 rounded border border-red-500/40 px-2 py-0.5 text-red-700 hover:bg-red-500/10 disabled:opacity-60 dark:text-red-300"
                data-testid="workspace-step-retry"
              >
                {retrying ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCw className="h-3 w-3" />}
                Retry step
              </button>
            )}
          </div>
        )}

        {hasDetails && step.status !== 'pending' && step.status !== 'running' && (
          <button
            onClick={() => setOpen((o) => !o)}
            className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
          >
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            Raw details
          </button>
        )}
        {open && (
          <div className="mt-1.5 space-y-2">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Request</div>
              <pre className="mt-0.5 max-h-40 overflow-auto rounded-md bg-muted/60 p-2 text-[11px] whitespace-pre-wrap break-words">
                {`${step.connector_id}.${step.tool}(${JSON.stringify(step.args || {}, null, 2)})`}
              </pre>
            </div>
            {step.raw && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{failed ? 'Error' : 'Response'}</div>
                <pre className="mt-0.5 max-h-56 overflow-auto rounded-md bg-muted/60 p-2 text-[11px] whitespace-pre-wrap break-words">{step.raw}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

/**
 * Live timeline for a Workspace run: plan -> steps -> per-step result.
 * `steps` is an ordered array of step events (latest state per id); `plan` is
 * {text, items}. Retry re-runs one tool call via POST /mcp/steps/retry and
 * shows the new result in place.
 */
export default function WorkspaceTimeline({ plan, steps, live = false }) {
  const [overrides, setOverrides] = useState({});
  const [retryingId, setRetryingId] = useState(null);
  const [collapsed, setCollapsed] = useState(false);

  if (!plan && (!steps || steps.length === 0)) return null;

  const merged = (steps || []).map((s) => overrides[s.id] || s);
  const done = merged.filter((s) => s.status === 'done').length;
  const failed = merged.filter((s) => s.status === 'failed').length;
  const running = merged.some((s) => s.status === 'running' || s.status === 'pending');

  const retry = async (step) => {
    setRetryingId(step.id);
    setOverrides((o) => ({ ...o, [step.id]: { ...step, status: 'running', friendly_error: null } }));
    try {
      const { data } = await api.post('/mcp/steps/retry', { connector_id: step.connector_id, tool: step.tool, args: step.args || {} });
      setOverrides((o) => ({ ...o, [step.id]: { ...data, id: step.id, index: step.index, title: step.title } }));
    } catch (e) {
      setOverrides((o) => ({
        ...o,
        [step.id]: { ...step, status: 'failed', friendly_error: e.response?.data?.detail || 'Retry failed — please try again in a moment.' },
      }));
    } finally {
      setRetryingId(null);
    }
  };

  return (
    <div className="mb-4 rounded-xl border border-border bg-card/60" data-testid="workspace-timeline">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left"
      >
        <ListChecks className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">{live && running ? 'Working on it…' : 'Workspace run'}</span>
        <span className="text-xs text-muted-foreground">
          {merged.length > 0 && `${done} of ${merged.length} step${merged.length === 1 ? '' : 's'} done`}
          {failed > 0 && ` · ${failed} failed`}
        </span>
        <span className="ml-auto text-muted-foreground">
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </span>
      </button>

      {!collapsed && (
        <div className="border-t border-border px-3.5 py-3 space-y-4">
          {plan?.items?.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1.5">Plan</div>
              <ol className="space-y-1 text-sm">
                {plan.items.map((item, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] text-primary">{i + 1}</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {merged.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Steps</div>
              <ul>
                {merged.map((s, i) => (
                  <Step key={s.id} step={s} last={i === merged.length - 1} onRetry={retry} retrying={retryingId === s.id} />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
