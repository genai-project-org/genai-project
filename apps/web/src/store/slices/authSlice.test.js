import { beforeEach, describe, expect, test } from 'vitest';
import reducer, { setAuth, setTokens, setUser, logout } from './authSlice';

describe('authSlice reducer', () => {
  const initialState = { user: null, access_token: null, refresh_token: null };

  // Fake-looking, obviously non-production values — never real credentials.
  const fakeUser = { id: 'user_1', name: 'Test User', email: 'test@example.invalid' };
  const fakeTokens = { access_token: 'fake-access-token', refresh_token: 'fake-refresh-token' };

  beforeEach(() => {
    localStorage.clear();
  });

  test('setAuth stores user + tokens and persists them', () => {
    const state = reducer(initialState, setAuth({ user: fakeUser, tokens: fakeTokens }));
    expect(state.user).toEqual(fakeUser);
    expect(state.access_token).toBe('fake-access-token');
    expect(state.refresh_token).toBe('fake-refresh-token');

    const persisted = JSON.parse(localStorage.getItem('iema_auth'));
    expect(persisted.user).toEqual(fakeUser);
    expect(persisted.tokens).toEqual(fakeTokens);
  });

  test('setTokens updates only the tokens and re-persists', () => {
    const authed = reducer(initialState, setAuth({ user: fakeUser, tokens: fakeTokens }));
    const state = reducer(authed, setTokens({ access_token: 'new-access', refresh_token: 'new-refresh' }));
    expect(state.user).toEqual(fakeUser); // untouched
    expect(state.access_token).toBe('new-access');
    expect(state.refresh_token).toBe('new-refresh');
  });

  test('setUser updates only the user', () => {
    const authed = reducer(initialState, setAuth({ user: fakeUser, tokens: fakeTokens }));
    const updated = { ...fakeUser, name: 'Renamed' };
    const state = reducer(authed, setUser(updated));
    expect(state.user).toEqual(updated);
    expect(state.access_token).toBe('fake-access-token');
  });

  test('logout clears user + tokens and removes persisted auth', () => {
    const authed = reducer(initialState, setAuth({ user: fakeUser, tokens: fakeTokens }));
    expect(localStorage.getItem('iema_auth')).not.toBeNull();

    const state = reducer(authed, logout());
    expect(state).toEqual({ user: null, access_token: null, refresh_token: null });
    expect(localStorage.getItem('iema_auth')).toBeNull();
  });
});
