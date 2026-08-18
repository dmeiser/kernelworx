/**
 * Tests for ForgotPasswordPage
 *
 * Covers the two-step Cognito password-reset flow:
 * 1. Request reset code.
 * 2. Confirm reset with code + new password.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ForgotPasswordPage } from './ForgotPasswordPage';
import * as amplifyAuth from 'aws-amplify/auth';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('aws-amplify/auth', () => ({
  resetPassword: vi.fn(),
  confirmResetPassword: vi.fn(),
}));

const renderPage = () => render(<ForgotPasswordPage />);

const setupUser = () => userEvent.setup({ delay: null });

const fillRequestForm = async (user: ReturnType<typeof setupUser>, email: string) => {
  await user.type(screen.getByLabelText(/^Email Address/i), email);
};

const submitRequestForm = async (user: ReturnType<typeof setupUser>) => {
  await user.click(screen.getByRole('button', { name: 'Send Reset Code' }));
};

const fillResetForm = async (
  user: ReturnType<typeof setupUser>,
  code: string,
  password: string,
  confirmPassword: string,
) => {
  await user.type(screen.getByLabelText(/^Reset Code/i), code);
  await user.type(screen.getByLabelText(/^New Password/i), password);
  await user.type(screen.getByLabelText(/^Confirm New Password/i), confirmPassword);
};

const submitResetForm = async (user: ReturnType<typeof setupUser>) => {
  await user.click(screen.getByRole('button', { name: 'Reset Password' }));
};

/**
 * Submit the currently rendered form directly.
 *
 * This bypasses browser HTML5 constraint validation, which jsdom enforces for
 * empty ``required`` fields and would otherwise prevent React's ``onSubmit``
 * handler from running.  We use it only for validation tests that exercise the
 * component's own error handling.
 */
const forceSubmitForm = () => {
  const form = document.querySelector('form');
  if (!form) {
    throw new Error('No form found in the document');
  }
  fireEvent.submit(form);
};

const createNamedError = (name: string, message: string = 'mock error') => {
  const error = new Error(message);
  error.name = name;
  return error;
};

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('request reset code', () => {
    it('renders the request-code form on initial load', () => {
      renderPage();

      expect(screen.getByText('Reset your password')).toBeInTheDocument();
      expect(screen.getByLabelText(/^Email Address/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Send Reset Code' })).toBeInTheDocument();
    });

    it('shows validation error when email is missing', async () => {
      renderPage();
      forceSubmitForm();

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Email is required');
      });

      expect(amplifyAuth.resetPassword).not.toHaveBeenCalled();
    });

    it('requests a reset code successfully and reveals the confirmation form', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.resetPassword).mockResolvedValue({} as any);

      renderPage();
      await fillRequestForm(user, 'user@example.com');
      await submitRequestForm(user);

      await waitFor(() => {
        expect(amplifyAuth.resetPassword).toHaveBeenCalledWith({ username: 'user@example.com' });
      });

      expect(screen.getByRole('alert')).toHaveTextContent('Reset code sent to user@example.com');
      expect(screen.getByLabelText(/^Reset Code/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^New Password/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^Confirm New Password/i)).toBeInTheDocument();
    });

    it('treats UserNotFoundException as success to avoid account enumeration', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.resetPassword).mockRejectedValue(
        createNamedError('UserNotFoundException', 'User does not exist'),
      );

      renderPage();
      await fillRequestForm(user, 'unknown@example.com');
      await submitRequestForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Reset code sent to unknown@example.com');
      });

      expect(screen.queryByText('UserNotFoundException')).not.toBeInTheDocument();
      expect(screen.getByLabelText(/^Reset Code/i)).toBeInTheDocument();
    });

    it('treats InvalidParameterException as success to avoid account enumeration', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.resetPassword).mockRejectedValue(
        createNamedError('InvalidParameterException', 'Bad parameter'),
      );

      renderPage();
      await fillRequestForm(user, 'user@example.com');
      await submitRequestForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Reset code sent to user@example.com');
      });

      expect(screen.queryByText('InvalidParameterException')).not.toBeInTheDocument();
      expect(screen.getByLabelText(/^Reset Code/i)).toBeInTheDocument();
    });

    it('displays a mapped error when resetPassword fails with LimitExceededException', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.resetPassword).mockRejectedValue(
        createNamedError('LimitExceededException', 'Too many attempts'),
      );

      renderPage();
      await fillRequestForm(user, 'user@example.com');
      await submitRequestForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Too many attempts. Please try again later.',
        );
      });
    });

    it('displays a generic error for unmapped resetPassword failures', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.resetPassword).mockRejectedValue(
        createNamedError('UnexpectedException', 'Something went wrong'),
      );

      renderPage();
      await fillRequestForm(user, 'user@example.com');
      await submitRequestForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Unable to send reset code. Please try again later.',
        );
      });

      expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument();
    });
  });

  describe('confirm reset password', () => {
    beforeEach(async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.resetPassword).mockResolvedValue({} as any);

      renderPage();
      await fillRequestForm(user, 'user@example.com');
      await submitRequestForm(user);

      await waitFor(() => {
        expect(screen.getByLabelText(/^Reset Code/i)).toBeInTheDocument();
      });
    });

    it('shows validation error when passwords are missing', async () => {
      forceSubmitForm();

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Password and confirmation are required',
        );
      });

      expect(amplifyAuth.confirmResetPassword).not.toHaveBeenCalled();
    });

    it('shows validation error when password does not meet complexity requirements', async () => {
      const user = setupUser();
      await fillResetForm(user, '123456', 'short', 'short');
      await submitResetForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Password must be at least 8 characters and include uppercase, lowercase, number, and symbol',
        );
      });
    });

    it('shows validation error when passwords do not match', async () => {
      const user = setupUser();
      await fillResetForm(user, '123456', 'ValidPass1!', 'DifferentPass1!');
      await submitResetForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Passwords do not match');
      });
    });

    it('confirms reset successfully and redirects to login after a delay', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.confirmResetPassword).mockResolvedValue(undefined);

      await fillResetForm(user, '123456', 'ValidPass1!', 'ValidPass1!');
      await submitResetForm(user);

      await waitFor(() => {
        expect(amplifyAuth.confirmResetPassword).toHaveBeenCalledWith({
          username: 'user@example.com',
          confirmationCode: '123456',
          newPassword: 'ValidPass1!',
        });
      });

      expect(screen.getByRole('alert')).toHaveTextContent(
        'Password reset successfully. Redirecting to login...',
      );

      await vi.advanceTimersByTimeAsync(1500);

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/login');
      });
    });

    it('displays mapped error for invalid verification code', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.confirmResetPassword).mockRejectedValue(
        createNamedError('CodeMismatchException', 'Code mismatch'),
      );

      await fillResetForm(user, '000000', 'ValidPass1!', 'ValidPass1!');
      await submitResetForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Invalid verification code. Please check and try again.',
        );
      });
    });

    it('treats confirmation UserNotFoundException as invalid code to avoid account enumeration', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.confirmResetPassword).mockRejectedValue(
        createNamedError('UserNotFoundException', 'User does not exist'),
      );

      await fillResetForm(user, '000000', 'ValidPass1!', 'ValidPass1!');
      await submitResetForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Invalid verification code. Please check and try again.',
        );
      });

      expect(screen.queryByText('UserNotFoundException')).not.toBeInTheDocument();
    });

    it('displays mapped error for expired verification code', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.confirmResetPassword).mockRejectedValue(
        createNamedError('ExpiredCodeException', 'Code expired'),
      );

      await fillResetForm(user, '000000', 'ValidPass1!', 'ValidPass1!');
      await submitResetForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Verification code expired. Please request a new code.',
        );
      });
    });

    it('displays mapped error for invalid password', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.confirmResetPassword).mockRejectedValue(
        createNamedError('InvalidPasswordException', 'Bad password'),
      );

      await fillResetForm(user, '123456', 'ValidPass1!', 'ValidPass1!');
      await submitResetForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Password does not meet requirements: minimum 8 characters with uppercase, lowercase, numbers, and symbols.',
        );
      });
    });

    it('displays a generic error for unmapped confirmResetPassword failures', async () => {
      const user = setupUser();
      vi.mocked(amplifyAuth.confirmResetPassword).mockRejectedValue(
        createNamedError('UnexpectedException', 'Confirmation failed'),
      );

      await fillResetForm(user, '123456', 'ValidPass1!', 'ValidPass1!');
      await submitResetForm(user);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(
          'Unable to reset password. Please try again later.',
        );
      });

      expect(screen.queryByText('Confirmation failed')).not.toBeInTheDocument();
    });
  });
});
