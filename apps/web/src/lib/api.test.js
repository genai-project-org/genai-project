// Unit tests for the central axios client's interceptor logic (token
// attachment, wallet-balance side effect, structured-error flattening,
// and the 401 refresh-and-retry dance). `axios` itself is mocked so this
// suite never makes a real network call — the request/response handlers
// are captured off the mock instance and invoked directly with fake
// request/response/error objects.
import { beforeEach, describe, expect, test, vi } from 'vitest';

const interceptors = vi.hoisted(() => ({
  request: null,
  responseFulfilled: null,
  responseRejected: null,
}));

vi.mock('axios', () => {
  const instance = vi.fn((config) => instance.__retry(config));
  instance.__retry = vi.fn();
  instance.interceptors = {
    request: { use: vi.fn((fn) => { interceptors.request = fn; }) },
    response: {
      use: vi.fn((onFulfilled, onRejected) => {
        interceptors.responseFulfilled = onFulfilled;
        interceptors.responseRejected = onRejected;
      }),
    },
  };
  const post = vi.fn();
  return {
    default: { create: vi.fn(() => instance), post },
    create: vi.fn(() => instance),
    post,
  };
});

import axios from 'axios';
import api from './api';
import { store } from '@/store/store';
import { setAuth, logout } from '@/store/slices/authSlice';

const fakeUser = { id: 'user_1', name: 'Test User', email: 'test@example.invalid' };

describe('api client interceptors', () => {
  beforeEach(() => {
    store.dispatch(logout());
    vi.clearAllMocks();
  });

  test('request interceptor attaches the bearer token from the store', () => {
    store.dispatch(setAuth({ user: fakeUser, tokens: { access_token: 'fake-token', refresh_token: 'fake-refresh' } }));
    const config = interceptors.request({ headers: {} });
    expect(config.headers.Authorization).toBe('Bearer fake-token');
  });

  test('request interceptor leaves headers untouched when logged out', () => {
    const config = interceptors.request({ headers: {} });
    expect(config.headers.Authorization).toBeUndefined();
  });

  test('response interceptor syncs wallet balance into the store when present', () => {
    const response = interceptors.responseFulfilled({ data: { balance: 42 } });
    expect(response.data.balance).toBe(42);
    expect(store.getState().ui.walletBalance).toBe(42);
  });

  test('response interceptor ignores responses without a numeric balance', () => {
    store.dispatch({ type: 'ui/setWalletBalance', payload: 7 });
    interceptors.responseFulfilled({ data: { balance: null } });
    expect(store.getState().ui.walletBalance).toBe(7);
  });

  test('flattens a structured FastAPI error detail object into a message string', async () => {
    const error = {
      response: { status: 400, data: { detail: { message: 'Insufficient credits' } } },
      config: {},
    };
    await expect(interceptors.responseRejected(error)).rejects.toBe(error);
    expect(error.response.data.detail).toBe('Insufficient credits');
  });

  test('leaves a plain string error detail alone', async () => {
    const error = { response: { status: 400, data: { detail: 'Bad request' } }, config: {} };
    await expect(interceptors.responseRejected(error)).rejects.toBe(error);
    expect(error.response.data.detail).toBe('Bad request');
  });

  test('401 with no refresh token logs out and rejects without retrying', async () => {
    const error = { response: { status: 401, data: {} }, config: { _retry: false } };
    await expect(interceptors.responseRejected(error)).rejects.toBe(error);
    expect(store.getState().auth.access_token).toBeNull();
    expect(axios.post).not.toHaveBeenCalled();
  });

  test('401 with a refresh token refreshes and retries the original request once', async () => {
    store.dispatch(setAuth({ user: fakeUser, tokens: { access_token: 'stale', refresh_token: 'fake-refresh' } }));
    axios.post.mockResolvedValueOnce({ data: { access_token: 'fresh-token', refresh_token: 'fake-refresh' } });
    api.__retry.mockResolvedValueOnce({ data: { ok: true } });

    const original = { _retry: false, headers: {} };
    const error = { response: { status: 401, data: {} }, config: original };

    const result = await interceptors.responseRejected(error);

    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining('/auth/refresh'),
      { refresh_token: 'fake-refresh' },
    );
    expect(store.getState().auth.access_token).toBe('fresh-token');
    expect(original._retry).toBe(true);
    expect(original.headers.Authorization).toBe('Bearer fresh-token');
    expect(api).toHaveBeenCalledWith(original);
    expect(result).toEqual({ data: { ok: true } });
  });

  test('401 retry logs out if the refresh call itself fails', async () => {
    store.dispatch(setAuth({ user: fakeUser, tokens: { access_token: 'stale', refresh_token: 'fake-refresh' } }));
    axios.post.mockRejectedValueOnce(new Error('refresh expired'));

    const original = { _retry: false, headers: {} };
    const error = { response: { status: 401, data: {} }, config: original };

    await expect(interceptors.responseRejected(error)).rejects.toBeInstanceOf(Error);
    expect(store.getState().auth.access_token).toBeNull();
  });
});
