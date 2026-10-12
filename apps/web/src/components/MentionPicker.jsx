import { useEffect, useRef } from 'react';
import { Plug, X } from 'lucide-react';
import { cn } from '@/lib/utils';

/** "@GitHub", "@GoogleCalendar" — the typed handle for a connector (generic, derived from its name). */
export function connectorHandle(c) {
  return c.display_name.replace(/[^A-Za-z0-9]/g, '');
}

/** Connector ids @-mentioned in `text`, in order of appearance. Works for any registry connector. */
export function extractMentions(text, connectors) {
  const found = [];
  for (const c of connectors || []) {
    const re = new RegExp(`(^|\\s)@${connectorHandle(c)}(?![A-Za-z0-9_])`, 'i');
    const m = re.exec(text);
    if (m) found.push({ id: c.id, at: m.index });
  }
  return found.sort((a, b) => a.at - b.at).map((f) => f.id);
}

/** The "@query" fragment right before the caret, or null when the caret isn't inside a mention. */
export function activeMention(text, caret) {
  const m = /(^|\s)@([A-Za-z0-9_]*)$/.exec(text.slice(0, caret));
  if (!m) return null;
  const query = m[2];
  return { query, start: caret - query.length - 1 };
}

export function filterConnectors(connectors, query) {
  const q = query.toLowerCase();
  const rank = (c) => (c.connected ? 0 : c.mcp_status === 'ready' ? 1 : 2);
  return (connectors || [])
    .filter((c) => !q || connectorHandle(c).toLowerCase().includes(q) || c.display_name.toLowerCase().includes(q))
    .sort((a, b) => rank(a) - rank(b) || a.display_name.localeCompare(b.display_name))
    .slice(0, 8);
}

function badge(c) {
  if (c.connected) return <span className="rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-700 dark:text-emerald-400">Connected</span>;
  if (c.mcp_status !== 'ready') return <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">Coming soon</span>;
  return <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">Not connected</span>;
}

export function MentionPopup({ items, index, onPick, onHover }) {
  const listRef = useRef(null);
  useEffect(() => {
    listRef.current?.children[index]?.scrollIntoView({ block: 'nearest' });
  }, [index]);
  if (!items.length) return null;
  return (
    <div
      ref={listRef}
      role="listbox"
      className="absolute bottom-full left-0 z-20 mb-2 max-h-64 w-72 overflow-auto rounded-lg border border-border bg-popover p-1 shadow-lg"
      data-testid="mention-popup"
    >
      {items.map((c, i) => (
        <button
          key={c.id}
          role="option"
          aria-selected={i === index}
          onMouseDown={(e) => { e.preventDefault(); onPick(c); }}
          onMouseEnter={() => onHover(i)}
          className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm', i === index && 'bg-accent')}
        >
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-semibold text-primary">
            {c.display_name.charAt(0).toUpperCase()}
          </span>
          <span className="flex-1 truncate">{c.display_name}</span>
          {badge(c)}
        </button>
      ))}
    </div>
  );
}

export function MentionChips({ ids, connectors, onRemove }) {
  if (!ids.length) return null;
  const byId = Object.fromEntries((connectors || []).map((c) => [c.id, c]));
  return (
    <div className="flex flex-wrap gap-1.5 px-3 pt-2" data-testid="mention-chips">
      {ids.map((id) => {
        const c = byId[id];
        if (!c) return null;
        return (
          <span
            key={id}
            className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
              c.connected ? 'border-primary/40 bg-primary/10 text-primary' : 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400')}
          >
            <Plug className="h-3 w-3" />@{c.display_name}
            {!c.connected && <span className="opacity-80">· not connected</span>}
            <button type="button" onClick={() => onRemove(c)} aria-label={`Remove ${c.display_name}`} className="ml-0.5 hover:opacity-70">
              <X className="h-3 w-3" />
            </button>
          </span>
        );
      })}
    </div>
  );
}
