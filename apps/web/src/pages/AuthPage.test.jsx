// Component tests for the login/register form. The central axios client
// (`@/lib/api`) and `sonner`'s toast are mocked so no real network call or
// visible toast UI is involved — assertions go through the Redux store
// (set up via renderWithProviders) and the mocked toast calls.
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/test-utils';
import AuthPage from './AuthPage';
import { AUTH } from '@/constants/testIds';

vi.mock('@/lib/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: { google: {}, apple: {}, github: {}, linkedin: {} } })),
    post: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import api from '@/lib/api';
import { toast } from 'sonner';

const fakeUser = { id: 'user_1', name: 'Test User', email: 'test@example.invalid' };
const fakeTokens = { access_token: 'fake-access', refresh_token: 'fake-refresh' };

describe('AuthPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({ data: { google: {}, apple: {}, github: {}, linkedin: {} } });
  });

  test('login mode shows email/password only, no name field', async () => {
    renderWithProviders(<AuthPage mode="login" />);
    expect(screen.getByText('Welcome back')).toBeInTheDocument();
    expect(screen.getByTestId(AUTH.emailInput)).toBeInTheDocument();
    expect(screen.getByTestId(AUTH.passwordInput)).toBeInTheDocument();
    expect(screen.queryByTestId(AUTH.nameInput)).not.toBeInTheDocument();
    expect(screen.getByTestId('auth-forgot-link')).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalled()); // let the oauth-config effect settle
  });

  test('register mode shows the name field and hides the forgot-password link', async () => {
    renderWithProviders(<AuthPage mode="register" />);
    expect(screen.getByText('Create your account')).toBeInTheDocument();
    expect(screen.getByTestId(AUTH.nameInput)).toBeInTheDocument();
    expect(screen.queryByTestId('auth-forgot-link')).not.toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
  });

  test('toggling password visibility switches the input type', async () => {
    renderWithProviders(<AuthPage mode="login" />);
    const passwordInput = screen.getByTestId(AUTH.passwordInput);
    expect(passwordInput).toHaveAttribute('type', 'password');
    fireEvent.click(screen.getByTestId('auth-password-toggle'));
    expect(passwordInput).toHaveAttribute('type', 'text');
    fireEvent.click(screen.getByTestId('auth-password-toggle'));
    expect(passwordInput).toHaveAttribute('type', 'password');
    await waitFor(() => expect(api.get).toHaveBeenCalled());
  });

  test('social sign-in buttons are disabled while oauth is not configured', async () => {
    renderWithProviders(<AuthPage mode="login" />);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/auth/oauth-config'));
    expect(screen.getByTestId('auth-apple-btn')).toBeDisabled();
    expect(screen.getByTestId('auth-github-btn')).toBeDisabled();
    expect(screen.getByTestId('auth-linkedin-btn')).toBeDisabled();
  });

  test('successful login posts credentials, stores auth, and shows a success toast', async () => {
    api.post.mockResolvedValueOnce({ data: { user: fakeUser, tokens: fakeTokens } });
    const { store } = renderWithProviders(<AuthPage mode="login" />);

    fireEvent.change(screen.getByTestId(AUTH.emailInput), { target: { value: 'test@example.invalid' } });
    fireEvent.change(screen.getByTestId(AUTH.passwordInput), { target: { value: 'hunter22' } });
    fireEvent.click(screen.getByTestId(AUTH.submitBtn));

    await waitFor(() => expect(store.getState().auth.user).toEqual(fakeUser));
    expect(api.post).toHaveBeenCalledWith('/auth/login', { email: 'test@example.invalid', password: 'hunter22' });
    expect(toast.success).toHaveBeenCalledWith('Welcome back');
  });

  test('failed login shows the server error message and does not touch the store', async () => {
    api.post.mockRejectedValueOnce({ response: { data: { detail: 'Invalid credentials' } } });
    const { store } = renderWithProviders(<AuthPage mode="login" />);

    fireEvent.change(screen.getByTestId(AUTH.emailInput), { target: { value: 'test@example.invalid' } });
    fireEvent.change(screen.getByTestId(AUTH.passwordInput), { target: { value: 'wrongpass' } });
    fireEvent.click(screen.getByTestId(AUTH.submitBtn));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Invalid credentials'));
    expect(store.getState().auth.user).toBeNull();
  });

  test('successful registration posts name/email/password and shows the welcome-credits toast', async () => {
    api.post.mockResolvedValueOnce({ data: { user: fakeUser, tokens: fakeTokens } });
    const { store } = renderWithProviders(<AuthPage mode="register" />);

    fireEvent.change(screen.getByTestId(AUTH.nameInput), { target: { value: 'Test User' } });
    fireEvent.change(screen.getByTestId(AUTH.emailInput), { target: { value: 'test@example.invalid' } });
    fireEvent.change(screen.getByTestId(AUTH.passwordInput), { target: { value: 'hunter22' } });
    fireEvent.click(screen.getByTestId(AUTH.submitBtn));

    await waitFor(() => expect(store.getState().auth.user).toEqual(fakeUser));
    expect(api.post).toHaveBeenCalledWith('/auth/register', {
      email: 'test@example.invalid',
      password: 'hunter22',
      name: 'Test User',
    });
    expect(toast.success).toHaveBeenCalledWith('Account created — enjoy your 100 welcome credits!');
  });

  test('the toggle link points to the other mode', async () => {
    renderWithProviders(<AuthPage mode="login" />);
    expect(screen.getByTestId(AUTH.toggleLink)).toHaveAttribute('href', '/register');
    await waitFor(() => expect(api.get).toHaveBeenCalled());
  });
});
