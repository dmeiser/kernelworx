/**
 * ForgotPasswordPage component tests
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { ForgotPasswordPage } from '../src/pages/ForgotPasswordPage';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: false, loading: false }),
}));

const resetPassword = vi.fn();
const confirmResetPassword = vi.fn();

vi.mock('aws-amplify/auth', () => ({
  resetPassword: (...args: unknown[]) => resetPassword(...args),
  confirmResetPassword: (...args: unknown[]) => confirmResetPassword(...args),
}));

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    resetPassword.mockClear();
    confirmResetPassword.mockClear();
  });

  test('renders the email step and submits a reset request', async () => {
    resetPassword.mockResolvedValueOnce({});

    render(
      <BrowserRouter>
        <ForgotPasswordPage />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Reset Password' })).toBeInTheDocument();

    const emailInput = screen.getByRole('textbox', { name: 'Email' });
    fireEvent.change(emailInput, { target: { value: 'user@example.com' } });

    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

    await waitFor(() => {
      expect(resetPassword).toHaveBeenCalledWith({ username: 'user@example.com' });
    });

    expect(screen.getByText(/If an account exists for user@example.com/)).toBeInTheDocument();
  });

  test('renders the confirmation step after requesting a code', async () => {
    resetPassword.mockResolvedValueOnce({});

    render(
      <BrowserRouter>
        <ForgotPasswordPage />
      </BrowserRouter>,
    );

    fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
      target: { value: 'user@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'Confirmation Code' })).toBeInTheDocument();
    });

    expect(screen.getByTestId('new-password')).toBeInTheDocument();
    expect(screen.getByTestId('confirm-password')).toBeInTheDocument();
  });

  test('shows validation error when passwords do not match', async () => {
    resetPassword.mockResolvedValueOnce({});

    render(
      <BrowserRouter>
        <ForgotPasswordPage />
      </BrowserRouter>,
    );

    fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
      target: { value: 'user@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'Confirmation Code' })).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('textbox', { name: 'Confirmation Code' }), {
      target: { value: '123456' },
    });
    fireEvent.change(screen.getByTestId('new-password'), {
      target: { value: 'Password123!' },
    });
    fireEvent.change(screen.getByTestId('confirm-password'), {
      target: { value: 'Different456!' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

    expect(await screen.findByText('Passwords do not match')).toBeInTheDocument();
    expect(confirmResetPassword).not.toHaveBeenCalled();
  });

  test('confirms reset and schedules a redirect on success', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    resetPassword.mockResolvedValueOnce({});
    confirmResetPassword.mockResolvedValueOnce({});

    try {
      render(
        <BrowserRouter>
          <ForgotPasswordPage />
        </BrowserRouter>,
      );

      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'user@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: 'Confirmation Code' })).toBeInTheDocument();
      });

      fireEvent.change(screen.getByRole('textbox', { name: 'Confirmation Code' }), {
        target: { value: '123456' },
      });
      fireEvent.change(screen.getByTestId('new-password'), {
        target: { value: 'Password123!' },
      });
      fireEvent.change(screen.getByTestId('confirm-password'), {
        target: { value: 'Password123!' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      await waitFor(() => {
        expect(confirmResetPassword).toHaveBeenCalledWith({
          username: 'user@example.com',
          confirmationCode: '123456',
          newPassword: 'Password123!',
        });
      });

      expect(screen.getByText('Your password has been reset successfully.')).toBeInTheDocument();

      await waitFor(
        () => {
          expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
        },
        { timeout: 3000 },
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
