// Component tests for the three-step (request code -> verify code -> set new
// password) recovery flow. `@/lib/api` and `sonner` are mocked so nothing
// touches the network; step transitions are driven purely by the mocked
// responses.
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import ForgotPassword from './ForgotPassword';

vi.mock('@/lib/api', () => ({
  default: { post: vi.fn() },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import api from '@/lib/api';
import { toast } from 'sonner';

function renderPage() {
  return render(<ForgotPassword />, { wrapper: MemoryRouter });
}

describe('ForgotPassword', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('request step: submitting an email asks the server for a code and advances to verify', async () => {
    api.post.mockResolvedValueOnce({ data: {} });
    renderPage();

    fireEvent.change(screen.getByTestId('forgot-email-input'), { target: { value: 'me@example.invalid' } });
    fireEvent.click(screen.getByTestId('forgot-submit-btn'));

    await waitFor(() => expect(screen.getByTestId('forgot-otp-input')).toBeInTheDocument());
    expect(api.post).toHaveBeenCalledWith('/auth/forgot-password', { email: 'me@example.invalid' });
    expect(toast.success).toHaveBeenCalled();
  });

  test('verify step: the verify button stays disabled until 6 digits are entered, and non-digits are stripped', async () => {
    api.post.mockResolvedValueOnce({ data: {} }); // forgot-password
    renderPage();
    fireEvent.change(screen.getByTestId('forgot-email-input'), { target: { value: 'me@example.invalid' } });
    fireEvent.click(screen.getByTestId('forgot-submit-btn'));
    await waitFor(() => expect(screen.getByTestId('forgot-otp-input')).toBeInTheDocument());

    const otpInput = screen.getByTestId('forgot-otp-input');
    const verifyBtn = screen.getByTestId('forgot-verify-btn');

    fireEvent.change(otpInput, { target: { value: '12a3b4' } });
    expect(otpInput).toHaveValue('1234'); // non-digits stripped
    expect(verifyBtn).toBeDisabled();

    fireEvent.change(otpInput, { target: { value: '123456' } });
    expect(otpInput).toHaveValue('123456');
    expect(verifyBtn).not.toBeDisabled();
  });

  test('an invalid code shows the server error and stays on the verify step', async () => {
    api.post.mockResolvedValueOnce({ data: {} }); // forgot-password
    renderPage();
    fireEvent.change(screen.getByTestId('forgot-email-input'), { target: { value: 'me@example.invalid' } });
    fireEvent.click(screen.getByTestId('forgot-submit-btn'));
    await waitFor(() => expect(screen.getByTestId('forgot-otp-input')).toBeInTheDocument());

    api.post.mockRejectedValueOnce({ response: { data: { detail: 'Invalid or expired code' } } });
    fireEvent.change(screen.getByTestId('forgot-otp-input'), { target: { value: '000000' } });
    fireEvent.click(screen.getByTestId('forgot-verify-btn'));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Invalid or expired code'));
    expect(screen.getByTestId('forgot-otp-input')).toBeInTheDocument(); // still on verify step
  });

  test('full happy path reaches the reset step and then the done screen', async () => {
    api.post
      .mockResolvedValueOnce({ data: {} }) // forgot-password
      .mockResolvedValueOnce({ data: { reset_token: 'tok_123' } }) // verify-reset-otp
      .mockResolvedValueOnce({ data: {} }); // reset-password
    renderPage();

    fireEvent.change(screen.getByTestId('forgot-email-input'), { target: { value: 'me@example.invalid' } });
    fireEvent.click(screen.getByTestId('forgot-submit-btn'));
    await waitFor(() => expect(screen.getByTestId('forgot-otp-input')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('forgot-otp-input'), { target: { value: '123456' } });
    fireEvent.click(screen.getByTestId('forgot-verify-btn'));
    await waitFor(() => expect(screen.getByTestId('forgot-new-password')).toBeInTheDocument());

    const saveBtn = screen.getByTestId('forgot-save-btn');
    expect(saveBtn).toBeDisabled(); // fewer than 8 chars so far

    fireEvent.change(screen.getByTestId('forgot-new-password'), { target: { value: 'longenoughpassword' } });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await waitFor(() => expect(screen.getByText('Password updated')).toBeInTheDocument());
    expect(api.post).toHaveBeenNthCalledWith(3, '/auth/reset-password', {
      token: 'tok_123',
      new_password: 'longenoughpassword',
    });
  });
});
