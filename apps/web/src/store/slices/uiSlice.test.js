import { beforeEach, describe, expect, test, vi } from 'vitest';
import reducer, {
  setTheme,
  toggleSidebar,
  setSidebar,
  setWalletBalance,
} from './uiSlice';

describe('uiSlice reducer', () => {
  const initialState = { theme: 'dark', sidebarCollapsed: false, walletBalance: null };

  beforeEach(() => {
    localStorage.clear();
  });

  test('returns the initial state for an unknown action', () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual(
      expect.objectContaining({ sidebarCollapsed: false, walletBalance: null }),
    );
  });

  test('setTheme updates theme and persists to localStorage', () => {
    const state = reducer(initialState, setTheme('light'));
    expect(state.theme).toBe('light');
    expect(localStorage.getItem('iema_theme')).toBe('light');
  });

  test('toggleSidebar flips sidebarCollapsed and persists it', () => {
    const state = reducer(initialState, toggleSidebar());
    expect(state.sidebarCollapsed).toBe(true);
    expect(localStorage.getItem('iema_sidebar')).toBe('1');

    const state2 = reducer(state, toggleSidebar());
    expect(state2.sidebarCollapsed).toBe(false);
    expect(localStorage.getItem('iema_sidebar')).toBe('0');
  });

  test('setSidebar sets sidebarCollapsed directly without touching storage', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');
    const state = reducer(initialState, setSidebar(true));
    expect(state.sidebarCollapsed).toBe(true);
    expect(setItemSpy).not.toHaveBeenCalled();
    setItemSpy.mockRestore();
  });

  test('setWalletBalance stores the numeric balance', () => {
    const state = reducer(initialState, setWalletBalance(1234));
    expect(state.walletBalance).toBe(1234);
  });

  test('does not throw when localStorage access fails', () => {
    const setItemSpy = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('storage disabled');
      });
    expect(() => reducer(initialState, setTheme('system'))).not.toThrow();
    setItemSpy.mockRestore();
  });
});
