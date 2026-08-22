/**
 * ForgotPasswordPage component tests
 */

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { ForgotPasswordPage } from '../src/pages/ForgotPasswordPage';
import { useAuth } from '../src/contexts/AuthContext';
import type { AuthContextValue } from '../src/types/auth';
import { resetPassword, confirmResetPassword } from 'aws-amplify/auth';
import type { ResetPasswordOutput } from 'aws-amplify/auth';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({ isAuthenticated: false, loading: false } as AuthContextValue)),
}));

vi.mock('aws-amplify/auth', () => ({
  resetPassword: vi.fn(),
  confirmResetPassword: vi.fn(),
}));

const createNamedError = (name: string, message = 'mock error') => {
  const error = new Error(message);
  error.name = name;
  return error;
};

const forceSubmitForm = () => {
  const form = document.querySelector('form');
  if (!form) {
    throw new Error('No form found in the document');
  }
  fireEvent.submit(form);
};

const renderPage = () =>
  render(
    <BrowserRouter>
      <ForgotPasswordPage />
    </BrowserRouter>,
  );

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: false, loading: false } as AuthContextValue);
    vi.mocked(resetPassword).mockResolvedValue({ isPasswordReset: false } as ResetPasswordOutput);
    vi.mocked(confirmResetPassword).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('redirects authenticated users to /home', async () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, loading: false } as AuthContextValue);
    renderPage();
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/home', { replace: true });
    });
  });

  describe('request reset code', () => {
    test('renders the request-code form on initial load', () => {
      renderPage();
      expect(screen.getByRole('heading', { name: 'Reset Password' })).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: 'Email' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Send Reset Code' })).toBeInTheDocument();
    });

    test('shows validation error when email is missing', async () => {
      renderPage();
      forceSubmitForm();
      expect(await screen.findByText('Please enter a valid email address')).toBeInTheDocument();
      expect(resetPassword).not.toHaveBeenCalled();
    });

    test('shows validation error when email is invalid', async () => {
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'not-an-email' },
      });
      forceSubmitForm();
      expect(await screen.findByText('Please enter a valid email address')).toBeInTheDocument();
    });

    test('requests a reset code successfully and reveals the confirmation form', async () => {
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'user@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

      await waitFor(() => {
        expect(resetPassword).toHaveBeenCalledWith({ username: 'user@example.com' });
      });

      expect(screen.getByRole('alert')).toHaveTextContent(
        'If an account exists for user@example.com, a reset code has been sent.',
      );
      expect(screen.getByRole('textbox', { name: 'Confirmation Code' })).toBeInTheDocument();
      expect(screen.getByTestId('new-password')).toBeInTheDocument();
      expect(screen.getByTestId('confirm-password')).toBeInTheDocument();
    });

    test('treats UserNotFoundException as success to avoid account enumeration', async () => {
      vi.mocked(resetPassword).mockRejectedValue(createNamedError('UserNotFoundException'));
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'unknown@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'If an account exists for unknown@example.com, a reset code has been sent.',
        );
      });
      expect(screen.getByRole('textbox', { name: 'Confirmation Code' })).toBeInTheDocument();
    });

    test('treats InvalidParameterException as success to avoid account enumeration', async () => {
      vi.mocked(resetPassword).mockRejectedValue(createNamedError('InvalidParameterException'));
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'user@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'If an account exists for user@example.com, a reset code has been sent.',
        );
      });
    });

    test('displays a mapped error when resetPassword fails with LimitExceededException', async () => {
      vi.mocked(resetPassword).mockRejectedValue(createNamedError('LimitExceededException'));
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'user@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Too many attempts. Please wait a while before trying again.',
      );
    });

    test('displays a generic error for unmapped resetPassword failures', async () => {
      vi.mocked(resetPassword).mockRejectedValue(createNamedError('UnexpectedException', ''));
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'user@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));

      expect(await screen.findByText('Unable to send reset code. Please try again.')).toBeInTheDocument();
    });

    test('can close the success alert after requesting a code', async () => {
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'user@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));
      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'If an account exists for user@example.com, a reset code has been sent.',
        );
      });

      fireEvent.click(screen.getByRole('button', { name: /close/i }));
      await waitFor(() => {
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      });
    });

    test('can go back to the email form and resend a code', async () => {
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'first@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));
      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: 'Confirmation Code' })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: 'Back to Email' }));
      expect(screen.getByRole('textbox', { name: 'Email' })).toBeInTheDocument();

      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'second@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));
      await waitFor(() => {
        expect(resetPassword).toHaveBeenLastCalledWith({ username: 'second@example.com' });
      });
    });
  });

  describe('confirm reset password', () => {
    beforeEach(async () => {
      renderPage();
      fireEvent.change(screen.getByRole('textbox', { name: 'Email' }), {
        target: { value: 'user@example.com' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Send Reset Code' }));
      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: 'Confirmation Code' })).toBeInTheDocument();
      });
    });

    test('shows validation error when passwords are missing', async () => {
      fireEvent.change(screen.getByRole('textbox', { name: 'Confirmation Code' }), {
        target: { value: '123456' },
      });
      forceSubmitForm();

      expect(await screen.findByText('Password and confirmation are required')).toBeInTheDocument();
      expect(confirmResetPassword).not.toHaveBeenCalled();
    });

    test('shows validation error when password does not meet complexity requirements', async () => {
      await fillResetForm('123456', 'short', 'short');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Password must be at least 8 characters and include uppercase, lowercase, number, and symbol',
      );
    });

    test('shows validation error when passwords do not match', async () => {
      await fillResetForm('123456', 'Password123!', 'Different456!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match');
    });

    test('confirms reset successfully and redirects to login after a delay', async () => {
      await fillResetForm('123456', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      await waitFor(() => {
        expect(confirmResetPassword).toHaveBeenCalledWith({
          username: 'user@example.com',
          confirmationCode: '123456',
          newPassword: 'Password123!',
        });
      });

      expect(screen.getByRole('alert')).toHaveTextContent(
        'Your password has been reset successfully.',
      );

      await waitFor(
        () => {
          expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
        },
        { timeout: 3000 },
      );
    });

    test('clears a scheduled redirect when going back to the email form', async () => {
      await fillResetForm('123456', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Your password has been reset successfully.',
        );
      });

      fireEvent.click(screen.getByRole('button', { name: 'Back to Email' }));
      expect(screen.getByRole('textbox', { name: 'Email' })).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    test('clears a previous redirect timer when resetting again', async () => {
      await fillResetForm('123456', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));
      await waitFor(
        () => {
          expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
        },
        { timeout: 3000 },
      );

      mockNavigate.mockClear();
      await fillResetForm('654321', 'NewPass123!', 'NewPass123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      await waitFor(() => {
        expect(confirmResetPassword).toHaveBeenLastCalledWith({
          username: 'user@example.com',
          confirmationCode: '654321',
          newPassword: 'NewPass123!',
        });
      });

      await waitFor(
        () => {
          expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
        },
        { timeout: 3000 },
      );
    });

    test('displays mapped error for invalid verification code', async () => {
      vi.mocked(confirmResetPassword).mockRejectedValue(createNamedError('CodeMismatchException'));
      await fillResetForm('000000', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Invalid confirmation code. Please check and try again.',
      );
    });

    test('treats confirmation UserNotFoundException as invalid code to avoid account enumeration', async () => {
      vi.mocked(confirmResetPassword).mockRejectedValue(createNamedError('UserNotFoundException'));
      await fillResetForm('000000', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Invalid confirmation code. Please check and try again.',
      );
    });

    test('displays mapped error for expired verification code', async () => {
      vi.mocked(confirmResetPassword).mockRejectedValue(createNamedError('ExpiredCodeException'));
      await fillResetForm('000000', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'This code has expired. Please request a new one.',
      );
    });

    test('displays mapped error for invalid password', async () => {
      vi.mocked(confirmResetPassword).mockRejectedValue(createNamedError('InvalidPasswordException'));
      await fillResetForm('123456', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Password does not meet requirements: minimum 8 characters with uppercase, lowercase, numbers, and symbols.',
      );
    });

    test('displays a generic error for unmapped confirmResetPassword failures', async () => {
      vi.mocked(confirmResetPassword).mockRejectedValue(createNamedError('UnexpectedException', ''));
      await fillResetForm('123456', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByText('Unable to reset password. Please try again.')).toBeInTheDocument();
    });

    test('clears errors and success alerts when closed', async () => {
      vi.mocked(confirmResetPassword).mockRejectedValue(createNamedError('CodeMismatchException'));
      await fillResetForm('000000', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));
      const alert = await screen.findByRole('alert');
      expect(alert).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /close/i }));
      await waitFor(() => {
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      });
    });

    test('shows validation error when confirmation code is empty', async () => {
      await fillResetForm('', 'Password123!', 'Password123!');
      forceSubmitForm();

      expect(await screen.findByText('Confirmation code is required')).toBeInTheDocument();
      expect(confirmResetPassword).not.toHaveBeenCalled();
    });

    test('shows validation error when confirmation code is not 6 digits', async () => {
      await fillResetForm('12345', 'Password123!', 'Password123!');
      fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }));

      expect(await screen.findByText('Confirmation code must be 6 digits')).toBeInTheDocument();
      expect(confirmResetPassword).not.toHaveBeenCalled();
    });

    test('renders a resend-code button on the confirmation step', async () => {
      expect(screen.getByRole('button', { name: 'Resend Code' })).toBeInTheDocument();
    });

    test('resends the reset code for the stored email', async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

      await waitFor(() => {
        expect(resetPassword).toHaveBeenLastCalledWith({ username: 'user@example.com' });
      });
      expect(screen.getByRole('alert')).toHaveTextContent(
        'If an account exists for user@example.com, a reset code has been sent.',
      );
    });

    test('disables resend-code button during cooldown', async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Resend code in/i })).toBeDisabled();
      });

      act(() => {
        vi.advanceTimersByTime(30000);
      });

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Resend Code' })).toBeEnabled();
      });
    });
  });

  test('navigates to login when Back to Login is clicked', () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));
    expect(mockNavigate).toHaveBeenCalledWith('/login');
  });
});

async function fillResetForm(code: string, password: string, confirmPassword: string) {
  fireEvent.change(screen.getByRole('textbox', { name: 'Confirmation Code' }), {
    target: { value: code },
  });
  fireEvent.change(screen.getByTestId('new-password'), { target: { value: password } });
  fireEvent.change(screen.getByTestId('confirm-password'), { target: { value: confirmPassword } });
}
