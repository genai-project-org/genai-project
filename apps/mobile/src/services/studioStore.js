/**
 * Module-level Studio state store. Keeps generation status (summarize /
 * image / video) alive even when the user switches tabs, backgrounds the
 * app, or the Studio component unmounts. React components subscribe via
 * `useStudioStore(kind)` and get re-rendered whenever the underlying job
 * transitions.
 *
 * Deliberately dependency-free (no zustand / redux) — we only need a tiny
 * pub-sub because there's exactly one Studio screen per app instance.
 */
import { useEffect, useState } from 'react';

const initial = () => ({
  status: 'idle',    // 'idle' | 'running' | 'done' | 'error'
  // per-kind input payload snapshot (so we can restore the form)
  // …plus whatever the runner writes into it.
});

const state = { sum: initial(), img: initial(), vid: initial() };
const listeners = new Set();

const emit = () => { listeners.forEach((l) => l()); };

export const studioStore = {
  get(kind) { return state[kind]; },
  anyRunning() {
    return Object.values(state).some((s) => s.status === 'running');
  },
  begin(kind, payload) {
    state[kind] = { ...initial(), ...payload, status: 'running' };
    emit();
  },
  complete(kind, patch) {
    state[kind] = { ...state[kind], ...patch, status: 'done' };
    emit();
  },
  fail(kind, error) {
    // Coerce FastAPI validation array-errors etc. so `<Text>{state.error}</Text>`
    // never throws "Objects are not valid as a React child".
    const msg = typeof error === 'string' ? error
      : Array.isArray(error) ? error.map((e) => e?.msg || JSON.stringify(e)).join(', ')
      : (error && typeof error === 'object' ? (error.msg || error.message || JSON.stringify(error)) : String(error));
    state[kind] = { ...state[kind], error: msg, status: 'error' };
    emit();
  },
  reset(kind) {
    state[kind] = initial();
    emit();
  },
  /** Reset any module that isn't currently generating. Called when the user
   * leaves the Studio screen so the form is empty on return — but a
   * running job is preserved so we can rejoin it. */
  resetIdle() {
    let changed = false;
    for (const k of Object.keys(state)) {
      if (state[k].status !== 'running') {
        state[k] = initial();
        changed = true;
      }
    }
    if (changed) emit();
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};

export function useStudioStore(kind) {
  const [, force] = useState(0);
  useEffect(() => studioStore.subscribe(() => force((n) => n + 1)), []);
  return state[kind];
}
