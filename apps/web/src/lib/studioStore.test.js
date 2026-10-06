// Unit tests for the module-scoped Studio state store. `state` is a plain
// module-level object shared across every test in this file (by design —
// it's what lets a generation survive navigation away from /studio), so
// each test resets the three keys it touches instead of relying on import
// isolation.
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { studioStore, useStudioStore } from './studioStore';

describe('studioStore', () => {
  beforeEach(() => {
    studioStore.reset('sum');
    studioStore.reset('img');
    studioStore.reset('vid');
  });

  test('get returns the idle state for a fresh module', () => {
    expect(studioStore.get('sum')).toEqual({ status: 'idle' });
  });

  test('anyRunning is false when every module is idle', () => {
    expect(studioStore.anyRunning()).toBe(false);
  });

  test('begin marks a module running and merges extra props', () => {
    studioStore.begin('sum', { prompt: 'hello' });
    expect(studioStore.get('sum')).toEqual({ status: 'running', prompt: 'hello' });
    expect(studioStore.anyRunning()).toBe(true);
  });

  test('complete marks a module done, keeping prior props and merging new ones', () => {
    studioStore.begin('img', { prompt: 'a cat' });
    studioStore.complete('img', { url: 'https://example.invalid/cat.png' });
    expect(studioStore.get('img')).toEqual({
      status: 'done',
      prompt: 'a cat',
      url: 'https://example.invalid/cat.png',
    });
  });

  test('fail stores a plain string error as-is', () => {
    studioStore.fail('sum', 'boom');
    expect(studioStore.get('sum')).toEqual({ status: 'error', error: 'boom' });
  });

  test('fail flattens a FastAPI-style array of validation errors', () => {
    studioStore.fail('sum', [{ msg: 'field required' }, { msg: 'too long' }]);
    expect(studioStore.get('sum').error).toBe('field required, too long');
  });

  test('fail falls back to JSON.stringify for array entries without msg', () => {
    studioStore.fail('sum', [{ code: 'X' }]);
    expect(studioStore.get('sum').error).toBe(JSON.stringify({ code: 'X' }));
  });

  test('fail extracts msg/message from a plain error object', () => {
    studioStore.fail('img', { message: 'network down' });
    expect(studioStore.get('img').error).toBe('network down');
  });

  test('fail stringifies a non-string, non-array, non-object error', () => {
    studioStore.fail('vid', 42);
    expect(studioStore.get('vid').error).toBe('42');
  });

  test('reset returns a module to idle', () => {
    studioStore.begin('sum', { prompt: 'x' });
    studioStore.reset('sum');
    expect(studioStore.get('sum')).toEqual({ status: 'idle' });
  });

  test('resetIdle clears non-running modules but preserves a running one', () => {
    studioStore.begin('sum', { prompt: 'keep me' });
    studioStore.complete('img', { url: 'done.png' });
    studioStore.resetIdle();
    expect(studioStore.get('sum')).toEqual({ status: 'running', prompt: 'keep me' });
    expect(studioStore.get('img')).toEqual({ status: 'idle' });
  });

  test('subscribe notifies listeners on every mutation, and unsubscribe stops it', () => {
    const listener = vi.fn();
    const unsubscribe = studioStore.subscribe(listener);

    studioStore.begin('sum', {});
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    studioStore.complete('sum', {});
    expect(listener).toHaveBeenCalledTimes(1); // no further calls after unsubscribing
  });

  test('useStudioStore re-renders when the watched module changes', () => {
    const { result } = renderHook(() => useStudioStore('sum'));
    expect(result.current).toEqual({ status: 'idle' });

    act(() => {
      studioStore.begin('sum', { prompt: 'hi' });
    });

    expect(result.current).toEqual({ status: 'running', prompt: 'hi' });
  });
});
