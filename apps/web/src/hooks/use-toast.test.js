import { act, renderHook } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { reducer, useToast } from './use-toast';

describe('toast reducer', () => {
  test('ADD_TOAST prepends and caps the list at TOAST_LIMIT (1)', () => {
    const s1 = reducer({ toasts: [] }, { type: 'ADD_TOAST', toast: { id: '1', open: true } });
    expect(s1.toasts).toHaveLength(1);

    const s2 = reducer(s1, { type: 'ADD_TOAST', toast: { id: '2', open: true } });
    // capped at 1, and the newest toast is the one kept
    expect(s2.toasts).toHaveLength(1);
    expect(s2.toasts[0].id).toBe('2');
  });

  test('UPDATE_TOAST merges fields into the matching toast only', () => {
    const state = { toasts: [{ id: '1', title: 'old', open: true }] };
    const next = reducer(state, { type: 'UPDATE_TOAST', toast: { id: '1', title: 'new' } });
    expect(next.toasts[0]).toEqual({ id: '1', title: 'new', open: true });
  });

  test('DISMISS_TOAST with an id marks only that toast closed', () => {
    const state = { toasts: [{ id: '1', open: true }, { id: '2', open: true }] };
    const next = reducer(state, { type: 'DISMISS_TOAST', toastId: '1' });
    expect(next.toasts.find((t) => t.id === '1').open).toBe(false);
    expect(next.toasts.find((t) => t.id === '2').open).toBe(true);
  });

  test('DISMISS_TOAST without an id closes every toast', () => {
    const state = { toasts: [{ id: '1', open: true }, { id: '2', open: true }] };
    const next = reducer(state, { type: 'DISMISS_TOAST', toastId: undefined });
    expect(next.toasts.every((t) => t.open === false)).toBe(true);
  });

  test('REMOVE_TOAST with an id removes just that toast', () => {
    const state = { toasts: [{ id: '1' }, { id: '2' }] };
    const next = reducer(state, { type: 'REMOVE_TOAST', toastId: '1' });
    expect(next.toasts).toEqual([{ id: '2' }]);
  });

  test('REMOVE_TOAST without an id clears all toasts', () => {
    const state = { toasts: [{ id: '1' }, { id: '2' }] };
    const next = reducer(state, { type: 'REMOVE_TOAST', toastId: undefined });
    expect(next.toasts).toEqual([]);
  });
});

describe('useToast hook', () => {
  test('toast() adds a toast visible to subscribed hook instances, dismiss() closes it', () => {
    const { result } = renderHook(() => useToast());

    act(() => {
      result.current.toast({ title: 'Hello' });
    });
    expect(result.current.toasts).toHaveLength(1);
    expect(result.current.toasts[0].title).toBe('Hello');
    expect(result.current.toasts[0].open).toBe(true);

    const toastId = result.current.toasts[0].id;
    act(() => {
      result.current.dismiss(toastId);
    });
    expect(result.current.toasts[0].open).toBe(false);
  });
});
