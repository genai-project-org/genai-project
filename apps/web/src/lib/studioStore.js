/**
 * Web Studio state store — same idea as the mobile one: module-scoped so
 * a generation survives tab switches inside Studio and even navigation
 * away from /studio and back. React re-subscribes via `useStudioStore`.
 */
import { useEffect, useState } from 'react';

const initial = () => ({ status: 'idle' });
const state = { sum: initial(), img: initial(), vid: initial() };
const listeners = new Set();
const emit = () => { listeners.forEach((l) => l()); };

export const studioStore = {
  get: (k) => state[k],
  anyRunning: () => Object.values(state).some((s) => s.status === 'running'),
  begin: (k, p) => { state[k] = { ...initial(), ...p, status: 'running' }; emit(); },
  complete: (k, p) => { state[k] = { ...state[k], ...p, status: 'done' }; emit(); },
  fail: (k, err) => {
    // FastAPI validation errors return `detail` as an array of objects.
    // Coerce anything non-string so `<Text>{state.error}</Text>` never
    // throws "Objects are not valid as a React child".
    const msg = typeof err === 'string' ? err
      : Array.isArray(err) ? err.map((e) => e?.msg || JSON.stringify(e)).join(', ')
      : (err && typeof err === 'object' ? (err.msg || err.message || JSON.stringify(err)) : String(err));
    state[k] = { ...state[k], error: msg, status: 'error' }; emit();
  },
  reset: (k) => { state[k] = initial(); emit(); },
  /** Reset any module that isn't currently generating. Called when the user
   * leaves the Studio screen so the form is empty on return — but a
   * running job is preserved so we can rejoin it. */
  resetIdle: () => {
    let changed = false;
    for (const k of Object.keys(state)) {
      if (state[k].status !== 'running') {
        state[k] = initial();
        changed = true;
      }
    }
    if (changed) emit();
  },
  subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
};

export function useStudioStore(k) {
  const [, force] = useState(0);
  useEffect(() => studioStore.subscribe(() => force((n) => n + 1)), []);
  return state[k];
}
