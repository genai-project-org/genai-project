import { useEffect, useMemo, useState } from 'react';
import api from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Loader2, Plus, Save, X } from 'lucide-react';
import { toast } from 'sonner';

const DIFFICULTY_COLOR = {
  Easy: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  Medium: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  Hard: 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30',
};

function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

// Local datetime input (yyyy-MM-ddTHH:mm) <-> ISO string, in the local tz —
// same convention Contest.jsx's original create form already used.
function isoToLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Admin-only contest create/edit form. Wired to the real POST/PATCH
 * /api/contest endpoints — no client-side-only mock state. The problem
 * picker reuses /api/practice/roadmap (the same source Roadmap.jsx renders
 * from) purely for its `step` grouping, so an admin sees the exact same
 * topic buckets a candidate would.
 *
 * `editingContest`: the currently-selected contest's detail payload (from
 * GET /contest/{id}) to prefill for editing, or null to create a new one.
 */
export default function ContestAdminPanel({ editingContest, onSaved, onClose }) {
  const [roadmap, setRoadmap] = useState([]);
  const [loadingProblems, setLoadingProblems] = useState(true);

  const [name, setName] = useState('');
  const [startAt, setStartAt] = useState('');
  const [endAt, setEndAt] = useState('');
  const [selected, setSelected] = useState(() => new Set());
  const [saving, setSaving] = useState(false);

  const isEdit = Boolean(editingContest);

  useEffect(() => {
    (async () => {
      setLoadingProblems(true);
      try {
        const { data } = await api.get('/practice/roadmap');
        setRoadmap(data.items || []);
      } catch (e) {
        toast.error(detailToString(e, 'Failed to load the problem bank'));
      } finally {
        setLoadingProblems(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (editingContest) {
      setName(editingContest.name || '');
      setStartAt(isoToLocalInput(editingContest.start_at));
      setEndAt(isoToLocalInput(editingContest.end_at));
      setSelected(new Set((editingContest.problems || []).map((p) => p.id)));
    } else {
      setName('');
      setStartAt('');
      setEndAt('');
      setSelected(new Set());
    }
  }, [editingContest]);

  const groups = useMemo(() => {
    const out = [];
    const byStep = new Map();
    for (const item of roadmap) {
      if (item.question_type !== 'code') continue; // contest submissions only support code problems
      if (!byStep.has(item.step)) {
        const bucket = { step: item.step, items: [] };
        byStep.set(item.step, bucket);
        out.push(bucket);
      }
      byStep.get(item.step).items.push(item);
    }
    return out;
  }, [roadmap]);

  const toggleProblem = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const canSave = name.trim() && startAt && endAt && selected.size > 0 && !saving;

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
        problem_ids: [...selected],
      };
      if (isEdit) {
        await api.patch(`/contest/${editingContest.id}`, payload);
        toast.success('Contest updated');
      } else {
        const { data } = await api.post('/contest/', payload);
        toast.success('Contest created');
        onSaved?.(data.id);
        return;
      }
      onSaved?.(editingContest.id);
    } catch (e) {
      toast.error(detailToString(e, isEdit ? 'Failed to update contest' : 'Failed to create contest'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-6 rounded-lg border border-border bg-card p-4 space-y-4" data-testid="contest-admin-form">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">{isEdit ? `Edit "${editingContest.name}"` : 'Create a new contest'}</div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} data-testid="contest-admin-close">
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">Contest name</Label>
        <Input placeholder="Contest name" value={name} onChange={(e) => setName(e.target.value)} data-testid="contest-new-name" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Start time</Label>
          <Input type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} data-testid="contest-new-start" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">End time</Label>
          <Input type="datetime-local" value={endAt} onChange={(e) => setEndAt(e.target.value)} data-testid="contest-new-end" />
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label className="text-xs text-muted-foreground">
            Problems ({selected.size} selected)
          </Label>
        </div>
        {loadingProblems ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-4 justify-center">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading problem bank…
          </div>
        ) : (
          <div className="max-h-72 overflow-y-auto rounded-md border border-border divide-y divide-border" data-testid="contest-problem-picker">
            {groups.map((group) => (
              <div key={group.step} className="p-2.5" data-testid={`contest-problem-picker-group-${group.step}`}>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                  {group.step}
                </div>
                <div className="space-y-1.5">
                  {group.items.map((p) => (
                    <label
                      key={p.id}
                      className="flex items-center gap-2.5 rounded px-1.5 py-1 hover:bg-accent/50 cursor-pointer"
                      data-testid={`contest-problem-picker-item-${p.id}`}
                    >
                      <Checkbox checked={selected.has(p.id)} onCheckedChange={() => toggleProblem(p.id)} />
                      <span className="flex-1 text-sm truncate">{p.title}</span>
                      <Badge variant="outline" className={DIFFICULTY_COLOR[p.difficulty] || ''}>{p.difficulty}</Badge>
                    </label>
                  ))}
                </div>
              </div>
            ))}
            {groups.length === 0 && (
              <p className="text-xs text-muted-foreground p-3 text-center">No problems available.</p>
            )}
          </div>
        )}
      </div>

      <Button size="sm" onClick={save} disabled={!canSave} data-testid="contest-admin-save">
        {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : isEdit ? <Save className="h-4 w-4 mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
        {isEdit ? 'Save changes' : 'Create contest'}
      </Button>
    </div>
  );
}
