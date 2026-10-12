import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/lib/api';

export function detailToString(err, fallback) {
  const d = err?.response?.data?.detail ?? err?.message;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join(', ');
  if (d && typeof d === 'object') return d.message || d.msg || JSON.stringify(d);
  return fallback;
}

// Local datetime input (yyyy-MM-ddTHH:mm) <-> ISO string, in the local tz.
export function isoToLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const localToIso = (v) => (v ? new Date(v).toISOString() : null);

export async function downloadBlob(path, filename) {
  const { data } = await api.get(path, { responseType: 'blob' });
  const url = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const DEFAULT_SETTINGS = {
  registration: { open: true, open_at: null, close_at: null, cap: 0, mode: 'both', min_team_size: 1, max_team_size: 3, access: 'public', access_code: '' },
  scoring: {
    mode: 'icpc', penalty_minutes_per_wrong: 0, wrong_penalty_points: 0, partial_scoring: true, first_solve_bonus: 0,
    speed_bonus_max: 0, speed_bonus_decay_minutes: 0, milestone_bonuses: [], global_grace_points: 0, global_grace_minutes: 0,
    max_attempts: 0, tie_breakers: ['time', 'last_solve', 'registered'],
  },
  leaderboard: { visibility: 'visible', freeze_minutes: 0, unfreeze_at_end: true, revealed: false },
  prizes: [],
  certificate: { enabled: true, winner_top_n: 0, participation_min_solved: 0, issue_after: 'anytime' },
  branding: { banner_url: '', description: '', rules_text: '', headline: '', tagline: '' },
  clarifications_enabled: true,
};

export const DEFAULT_PROBLEM_CONFIG = {
  points: 100, time_limit_ms: null, memory_limit_mb: null, allowed_languages: null, test_weights: null,
  visible_tests: null, release_at: null, release_after_minutes: null, max_attempts: null,
  first_solve_bonus: null, speed_bonus_max: null, hidden: false,
};

// Deep-merge stored settings over the defaults so every control has a value.
export function withDefaults(stored) {
  const out = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
  for (const [k, v] of Object.entries(stored || {})) {
    if (v && typeof v === 'object' && !Array.isArray(v) && out[k] && typeof out[k] === 'object') Object.assign(out[k], v);
    else out[k] = v;
  }
  return out;
}

export function Field({ label, hint, children, className = '' }) {
  return (
    <div className={`space-y-1 ${className}`}>
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function NumField({ label, hint, value, onChange, min = 0, max, step = 1, nullable = false, testid, placeholder }) {
  return (
    <Field label={label} hint={hint}>
      <Input
        type="number" min={min} max={max} step={step} value={value ?? ''} placeholder={placeholder}
        data-testid={testid}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === '') onChange(nullable ? null : 0);
          else onChange(Number(raw));
        }}
      />
    </Field>
  );
}

export function ToggleField({ label, hint, checked, onChange, testid }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2">
      <div>
        <div className="text-sm">{label}</div>
        {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
      </div>
      <Switch checked={!!checked} onCheckedChange={onChange} data-testid={testid} />
    </div>
  );
}

export function SelectField({ label, hint, value, onChange, options, testid }) {
  return (
    <Field label={label} hint={hint}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger data-testid={testid}><SelectValue /></SelectTrigger>
        <SelectContent>
          {options.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
        </SelectContent>
      </Select>
    </Field>
  );
}

export function Section({ title, children, hint }) {
  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div>
        <div className="text-sm font-medium">{title}</div>
        {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  );
}
