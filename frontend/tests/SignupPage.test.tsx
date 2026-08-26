/**
 * SignupPage component tests focused on resend verification code flow
 */

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { SignupPage } from '../src/pages/SignupPage';
import { useAuth } from '../src/contexts/AuthContext';
import type { AuthContextValue } from '../src/types/auth';
import { signUp, confirmSignUp, autoSignIn, fetchAuthSession, resendSignUpCode } from 'aws-amplify/auth';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: vi.fn(
    () => ({ isAuthenticated: false, loading: false, refreshSession: vi.fn() }) as unknown as AuthContextValue,
  ),
}));

vi.mock('aws-amplify/auth', () => ({
  signUp: vi.fn(),
  confirmSignUp: vi.fn(),
  autoSignIn: vi.fn(),
  fetchAuthSession: vi.fn(),
  resendSignUpCode: vi.fn(),
}));

vi.mock('@apollo/client/react', () => ({
  useMutation: vi.fn(() => [vi.fn(() => Promise.resolve({ data: {} }))]),
}));

const createNamedError = (name: string, message = 'mock error') => {
  const error = new Error(message);
  error.name = name;
  return error;
};

const renderPage = () =>
  render(
    <BrowserRouter>
      <SignupPage />
    </BrowserRouter>,
  );

const fillSignupForm = () => {
  const [passwordInput, confirmPasswordInput] = document.querySelectorAll('input[type="password"]');
  if (!passwordInput || !confirmPasswordInput) {
    throw new Error('Password inputs not found');
  }

  fireEvent.change(screen.getByRole('textbox', { name: 'Email Address' }), {
    target: { value: 'user@example.com' },
  });
  fireEvent.change(passwordInput, { target: { value: 'Password123!' } });
  fireEvent.change(confirmPasswordInput, { target: { value: 'Password123!' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /13 years of age or older/i }));
};

const submitSignupForm = async () => {
  vi.mocked(signUp).mockResolvedValue({
    isSignUpComplete: false,
    nextStep: { signUpStep: 'CONFIRM_SIGN_UP' },
  } as Awaited<ReturnType<typeof signUp>>);

  fillSignupForm();
  fireEvent.click(screen.getByRole('button', { name: 'Create Account' }));

  await waitFor(() => {
    expect(screen.getByRole('heading', { name: 'Verify Email' })).toBeInTheDocument();
  });
};

describe('SignupPage resend verification code', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      loading: false,
      refreshSession: vi.fn(),
    } as unknown as AuthContextValue);
    vi.mocked(signUp).mockResolvedValue({
      isSignUpComplete: false,
      nextStep: { signUpStep: 'CONFIRM_SIGN_UP' },
    } as Awaited<ReturnType<typeof signUp>>);
    vi.mocked(confirmSignUp).mockResolvedValue({ isSignUpComplete: true } as Awaited<ReturnType<typeof confirmSignUp>>);
    vi.mocked(autoSignIn).mockResolvedValue({} as Awaited<ReturnType<typeof autoSignIn>>);
    vi.mocked(fetchAuthSession).mockResolvedValue({} as Awaited<ReturnType<typeof fetchAuthSession>>);
    vi.mocked(resendSignUpCode).mockResolvedValue({} as Awaited<ReturnType<typeof resendSignUpCode>>);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('renders a Resend Code button on the verification step', async () => {
    renderPage();
    await submitSignupForm();

    expect(screen.getByRole('button', { name: 'Resend Code' })).toBeInTheDocument();
  });

  test('calls Amplify resendSignUpCode with the signup email and shows success', async () => {
    renderPage();
    await submitSignupForm();

    fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

    await waitFor(() => {
      expect(resendSignUpCode).toHaveBeenCalledWith({ username: 'user@example.com' });
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Verification code resent. Please check your email.');
  });

  test('disables the Resend Code button while the request is in flight', async () => {
    let resolveResend!: (value: Awaited<ReturnType<typeof resendSignUpCode>>) => void;
    vi.mocked(resendSignUpCode).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveResend = resolve;
        }),
    );

    renderPage();
    await submitSignupForm();

    const resendButton = screen.getByRole('button', { name: 'Resend Code' });
    fireEvent.click(resendButton);

    await waitFor(() => {
      expect(resendButton).toBeDisabled();
    });

    resolveResend({} as Awaited<ReturnType<typeof resendSignUpCode>>);
    await waitFor(() => {
      expect(resendButton).toBeEnabled();
    });
  });

  test('displays mapped LimitExceededException error', async () => {
    vi.mocked(resendSignUpCode).mockRejectedValue(createNamedError('LimitExceededException'));

    renderPage();
    await submitSignupForm();

    fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts. Please try again later');
  });

  test('displays mapped UserNotFoundException error', async () => {
    vi.mocked(resendSignUpCode).mockRejectedValue(createNamedError('UserNotFoundException'));

    renderPage();
    await submitSignupForm();

    fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No account found with this email address');
  });

  test('displays a generic error for unmapped resendSignUpCode failures', async () => {
    vi.mocked(resendSignUpCode).mockRejectedValue(createNamedError('UnexpectedException', 'Something broke'));

    renderPage();
    await submitSignupForm();

    fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Something broke');
  });

  test('clears a previous error when resend succeeds', async () => {
    vi.mocked(resendSignUpCode)
      .mockRejectedValueOnce(createNamedError('LimitExceededException'))
      .mockResolvedValueOnce({} as Awaited<ReturnType<typeof resendSignUpCode>>);

    renderPage();
    await submitSignupForm();

    fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts');

    fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Verification code resent');
    });
  });
});
