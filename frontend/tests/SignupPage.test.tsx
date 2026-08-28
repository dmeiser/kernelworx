/**
 * Comprehensive SignupPage component tests covering:
 * - Form validation and input handling
 * - Registration with/without optional fields
 * - Step transitions (CONFIRM_SIGN_UP, DONE)
 * - Email verification and auto-sign-in flows
 * - Optional fields mutation error resilience
 * - Auth session fallback when auto-sign-in fails
 * - Resend verification code handling
 * - Navigation links and cleanup on unmount
 */

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { SignupPage } from '../src/pages/SignupPage';
import { useAuth } from '../src/contexts/AuthContext';
import type { AuthContextValue } from '../src/types/auth';
import { signUp, confirmSignUp, autoSignIn, fetchAuthSession, resendSignUpCode } from 'aws-amplify/auth';

const mockNavigate = vi.fn();
const mockUpdateMyAccount = vi.fn();

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
  useMutation: vi.fn(() => [mockUpdateMyAccount]),
}));

const createNamedError = (name?: string, message = 'mock error') => {
  const error = new Error(message);
  if (name) {
    error.name = name;
  }
  return error;
};

const renderPage = () =>
  render(
    <BrowserRouter>
      <SignupPage />
    </BrowserRouter>,
  );

interface FormOverrides {
  email?: string;
  password?: string;
  confirmPassword?: string;
  ageConfirmed?: boolean;
  givenName?: string;
  familyName?: string;
  city?: string;
  state?: string;
  unitType?: string;
  unitNumber?: string;
}

const setTextInput = (name: string, value?: string) => {
  if (value !== undefined) {
    fireEvent.change(screen.getByRole('textbox', { name }), {
      target: { value },
    });
  }
};

const setSelectOption = (labelRegex: RegExp, value?: string) => {
  if (value !== undefined) {
    const combobox = screen.getByRole('combobox', { name: labelRegex });
    fireEvent.mouseDown(combobox);
    const option = screen.getByRole('option', { name: new RegExp(value, 'i') });
    fireEvent.click(option);
  }
};

const setNumberInput = (value?: string) => {
  const unitNumberInput = document.querySelector('input[type="number"]');
  if (value !== undefined && unitNumberInput) {
    fireEvent.change(unitNumberInput, {
      target: { value },
    });
  }
};

const setPasswordInputs = (password?: string, confirmPassword?: string) => {
  const [passwordInput, confirmPasswordInput] = document.querySelectorAll('input[type="password"]');
  if (password !== undefined && passwordInput) {
    fireEvent.change(passwordInput, { target: { value: password } });
  }
  if (confirmPassword !== undefined && confirmPasswordInput) {
    fireEvent.change(confirmPasswordInput, { target: { value: confirmPassword } });
  }
};

const setAgeCheckbox = (ageConfirmed = true) => {
  const checkbox = screen.getByRole('checkbox', { name: /13 years of age or older/i }) as HTMLInputElement;
  if (checkbox.checked !== ageConfirmed) {
    fireEvent.click(checkbox);
  }
};

const applyOptionalFormValues = (overrides?: FormOverrides) => {
  if (!overrides) {
    return;
  }
  setTextInput('First Name', overrides.givenName);
  setTextInput('Last Name', overrides.familyName);
  setTextInput('City', overrides.city);
  setTextInput('State', overrides.state);
  setSelectOption(/Unit Type/i, overrides.unitType);
  setNumberInput(overrides.unitNumber);
};

const fillSignupForm = (overrides?: FormOverrides) => {
  const merged = Object.assign(
    {
      email: 'user@example.com',
      password: 'Password123!',
      confirmPassword: 'Password123!',
      ageConfirmed: true,
    },
    overrides,
  );

  setTextInput('Email Address', merged.email);
  setPasswordInputs(merged.password, merged.confirmPassword);
  setAgeCheckbox(merged.ageConfirmed);
  applyOptionalFormValues(overrides);
};

const submitForm = (buttonName = 'Create Account') => {
  const button = screen.getByRole('button', { name: buttonName });
  fireEvent.submit(button.closest('form')!);
};

const submitSignupForm = async (
  overrides?: FormOverrides,
  signUpResult: Awaited<ReturnType<typeof signUp>> = {
    isSignUpComplete: false,
    nextStep: { signUpStep: 'CONFIRM_SIGN_UP' },
  } as Awaited<ReturnType<typeof signUp>>,
) => {
  vi.mocked(signUp).mockResolvedValue(signUpResult);

  fillSignupForm(overrides);
  submitForm('Create Account');

  if (signUpResult.nextStep?.signUpStep === 'CONFIRM_SIGN_UP') {
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Verify Email' })).toBeInTheDocument();
    });
  } else {
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create Account' })).toBeInTheDocument();
    });
  }
};

describe('SignupPage', () => {
  const mockRefreshSession = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockRefreshSession.mockResolvedValue(undefined);
    mockUpdateMyAccount.mockResolvedValue({ data: {} });
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      loading: false,
      refreshSession: mockRefreshSession,
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

  describe('Form rendering and navigation', () => {
    test('renders form fields, title, and handles uppercase state conversion', () => {
      renderPage();

      expect(screen.getByRole('heading', { name: 'Create Account' })).toBeInTheDocument();
      expect(screen.getByText('Join KernelWorx to manage your popcorn sales')).toBeInTheDocument();

      const stateInput = screen.getByRole('textbox', { name: 'State' });
      fireEvent.change(stateInput, { target: { value: 'ca' } });
      expect((stateInput as HTMLInputElement).value).toBe('CA');
    });

    test('updates unitType select field value', () => {
      renderPage();

      const combobox = screen.getByRole('combobox', { name: /Unit Type/i });
      fireEvent.mouseDown(combobox);
      const option = screen.getByRole('option', { name: /Pack/i });
      fireEvent.click(option);

      expect(screen.getByText('Pack (Cub Scouts)')).toBeInTheDocument();
    });

    test('navigates to login when Sign In link is clicked', () => {
      renderPage();

      fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  describe('Validation', () => {
    test('shows error when required fields are missing', async () => {
      renderPage();

      submitForm('Create Account');
      expect(await screen.findByText('Email and password are required')).toBeInTheDocument();
      expect(signUp).not.toHaveBeenCalled();
    });

    test('shows error when email does not contain @', async () => {
      renderPage();

      fillSignupForm({ email: 'invalid-email' });
      submitForm('Create Account');

      expect(await screen.findByText('Please enter a valid email address')).toBeInTheDocument();
      expect(signUp).not.toHaveBeenCalled();
    });

    test('shows error when password does not meet complexity requirements', async () => {
      renderPage();

      fillSignupForm({ password: 'simple', confirmPassword: 'simple' });
      submitForm('Create Account');

      expect(
        await screen.findByText(
          'Password must be at least 8 characters and include uppercase, lowercase, number, and symbol',
        ),
      ).toBeInTheDocument();
      expect(signUp).not.toHaveBeenCalled();
    });

    test('shows error when passwords do not match', async () => {
      renderPage();

      fillSignupForm({ password: 'Password123!', confirmPassword: 'DifferentPassword123!' });
      submitForm('Create Account');

      expect(await screen.findByText('Passwords do not match')).toBeInTheDocument();
      expect(signUp).not.toHaveBeenCalled();
    });

    test('shows error when age confirmation is unchecked', async () => {
      renderPage();

      fillSignupForm({ ageConfirmed: false });
      submitForm('Create Account');

      expect(await screen.findByText('You must be 13 years or older to create an account')).toBeInTheDocument();
      expect(signUp).not.toHaveBeenCalled();
    });
  });

  describe('Signup submission and steps', () => {
    test('passes givenName and familyName in userAttributes when provided', async () => {
      renderPage();

      await submitSignupForm({
        givenName: 'Jane',
        familyName: 'Doe',
      });

      expect(signUp).toHaveBeenCalledWith({
        username: 'user@example.com',
        password: 'Password123!',
        options: {
          userAttributes: {
            email: 'user@example.com',
            given_name: 'Jane',
            family_name: 'Doe',
          },
          autoSignIn: true,
        },
      });
    });

    test('handles DONE step by showing success and scheduling redirect to login', async () => {
      renderPage();

      await submitSignupForm(
        {},
        {
          isSignUpComplete: true,
          nextStep: { signUpStep: 'DONE' },
        } as Awaited<ReturnType<typeof signUp>>,
      );

      expect(screen.getByText('Account created successfully!')).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(1500);
      });

      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });

    test('displays mapped UsernameExistsException error', async () => {
      vi.mocked(signUp).mockRejectedValue(createNamedError('UsernameExistsException'));

      renderPage();
      fillSignupForm();
      submitForm('Create Account');

      expect(await screen.findByText('An account with this email already exists')).toBeInTheDocument();
    });

    test('displays mapped InvalidPasswordException error', async () => {
      vi.mocked(signUp).mockRejectedValue(createNamedError('InvalidPasswordException'));

      renderPage();
      fillSignupForm();
      submitForm('Create Account');

      expect(
        await screen.findByText(
          'Password does not meet requirements: minimum 8 characters with uppercase, lowercase, numbers, and symbols',
        ),
      ).toBeInTheDocument();
    });

    test('displays mapped InvalidParameterException error', async () => {
      vi.mocked(signUp).mockRejectedValue(createNamedError('InvalidParameterException'));

      renderPage();
      fillSignupForm();
      submitForm('Create Account');

      expect(await screen.findByText('Invalid input. Please check your information')).toBeInTheDocument();
    });

    test('displays custom error message for unmapped errors with a message', async () => {
      vi.mocked(signUp).mockRejectedValue(new Error('Network connectivity lost'));

      renderPage();
      fillSignupForm();
      submitForm('Create Account');

      expect(await screen.findByText('Network connectivity lost')).toBeInTheDocument();
    });

    test('displays generic fallback when error has no message or mapped name', async () => {
      vi.mocked(signUp).mockRejectedValue({});

      renderPage();
      fillSignupForm();
      submitForm('Create Account');

      expect(await screen.findByText('Signup failed. Please try again')).toBeInTheDocument();
    });
  });

  describe('Verification flow', () => {
    test('navigates to login when Back to Login is clicked in verification view', async () => {
      renderPage();
      await submitSignupForm();

      fireEvent.click(screen.getByRole('button', { name: 'Back to Login' }));
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });

    test('successful email verification with optional fields persists metadata and navigates to /home', async () => {
      renderPage();
      await submitSignupForm({
        givenName: 'John',
        familyName: 'Smith',
        city: 'Austin',
        state: 'TX',
        unitType: 'Pack',
        unitNumber: '101',
      });

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '123456' },
      });
      submitForm('Verify Email');

      await waitFor(() => {
        expect(confirmSignUp).toHaveBeenCalledWith({
          username: 'user@example.com',
          confirmationCode: '123456',
        });
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(autoSignIn).toHaveBeenCalled();
      expect(mockUpdateMyAccount).toHaveBeenCalledWith({
        variables: {
          input: {
            givenName: 'John',
            familyName: 'Smith',
            city: 'Austin',
            state: 'TX',
            unitType: 'Pack',
            unitNumber: 101,
          },
        },
      });
      expect(mockRefreshSession).toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith('/home');
    });

    test('successful email verification without optional fields skips mutation', async () => {
      renderPage();
      await submitSignupForm();

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '123456' },
      });
      submitForm('Verify Email');

      await waitFor(() => {
        expect(confirmSignUp).toHaveBeenCalled();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(autoSignIn).toHaveBeenCalled();
      expect(mockUpdateMyAccount).not.toHaveBeenCalled();
      expect(mockRefreshSession).toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith('/home');
    });

    test('mutation failure during optional fields save does not block home navigation', async () => {
      mockUpdateMyAccount.mockRejectedValue(new Error('Mutation failed'));

      renderPage();
      await submitSignupForm({ givenName: 'John' });

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '123456' },
      });
      submitForm('Verify Email');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(mockUpdateMyAccount).toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith('/home');
    });

    test('falls back to fetchAuthSession when autoSignIn fails but session exists', async () => {
      vi.mocked(autoSignIn).mockRejectedValue(new Error('AutoSignIn not enabled'));
      vi.mocked(fetchAuthSession).mockResolvedValue({} as Awaited<ReturnType<typeof fetchAuthSession>>);

      renderPage();
      await submitSignupForm();

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '123456' },
      });
      submitForm('Verify Email');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(fetchAuthSession).toHaveBeenCalled();
      expect(mockRefreshSession).toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith('/home');
    });

    test('redirects to login when autoSignIn fails and user is not authenticated', async () => {
      vi.mocked(autoSignIn).mockRejectedValue(new Error('AutoSignIn not enabled'));
      vi.mocked(fetchAuthSession).mockRejectedValue(new Error('No session'));

      renderPage();
      await submitSignupForm();

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '123456' },
      });
      submitForm('Verify Email');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });

      expect(screen.getByText('Please log in with your new account')).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(1500);
      });

      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });

    test('returns early if confirmSignUp indicates isSignUpComplete is false', async () => {
      vi.mocked(confirmSignUp).mockResolvedValue({ isSignUpComplete: false } as Awaited<
        ReturnType<typeof confirmSignUp>
      >);

      renderPage();
      await submitSignupForm();

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '123456' },
      });
      submitForm('Verify Email');

      await waitFor(() => {
        expect(confirmSignUp).toHaveBeenCalled();
      });

      expect(autoSignIn).not.toHaveBeenCalled();
      expect(mockNavigate).not.toHaveBeenCalled();
    });

    test('displays mapped CodeMismatchException error', async () => {
      vi.mocked(confirmSignUp).mockRejectedValue(createNamedError('CodeMismatchException'));

      renderPage();
      await submitSignupForm();

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '000000' },
      });
      submitForm('Verify Email');

      expect(
        await screen.findByText('Invalid verification code. Please check and try again'),
      ).toBeInTheDocument();
    });

    test('displays mapped ExpiredCodeException error', async () => {
      vi.mocked(confirmSignUp).mockRejectedValue(createNamedError('ExpiredCodeException'));

      renderPage();
      await submitSignupForm();

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '000000' },
      });
      submitForm('Verify Email');

      expect(
        await screen.findByText('Verification code expired. Please request a new one'),
      ).toBeInTheDocument();
    });

    test('displays fallback verification error when error object has no name or message', async () => {
      vi.mocked(confirmSignUp).mockRejectedValue({});

      renderPage();
      await submitSignupForm();

      fireEvent.change(screen.getByRole('textbox', { name: 'Verification Code' }), {
        target: { value: '000000' },
      });
      submitForm('Verify Email');

      expect(await screen.findByText('Verification failed. Please try again')).toBeInTheDocument();
    });
  });

  describe('Resend verification code', () => {
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
      expect(screen.getByText('Verification code resent. Please check your email.')).toBeInTheDocument();
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

      expect(await screen.findByText('Too many attempts. Please try again later')).toBeInTheDocument();
    });

    test('displays mapped UserNotFoundException error', async () => {
      vi.mocked(resendSignUpCode).mockRejectedValue(createNamedError('UserNotFoundException'));

      renderPage();
      await submitSignupForm();

      fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

      expect(await screen.findByText('No account found with this email address')).toBeInTheDocument();
    });

    test('displays a generic error for unmapped resendSignUpCode failures', async () => {
      vi.mocked(resendSignUpCode).mockRejectedValue(createNamedError('UnexpectedException', 'Something broke'));

      renderPage();
      await submitSignupForm();

      fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));

      expect(await screen.findByText('Something broke')).toBeInTheDocument();
    });

    test('clears a previous error when resend succeeds', async () => {
      vi.mocked(resendSignUpCode)
        .mockRejectedValueOnce(createNamedError('LimitExceededException'))
        .mockResolvedValueOnce({} as Awaited<ReturnType<typeof resendSignUpCode>>);

      renderPage();
      await submitSignupForm();

      fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));
      expect(await screen.findByText('Too many attempts. Please try again later')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Resend Code' }));
      await waitFor(() => {
        expect(screen.getByText('Verification code resent. Please check your email.')).toBeInTheDocument();
      });
    });
  });

  describe('Timer and unmount cleanup', () => {
    test('cleans up redirect timer on unmount', async () => {
      const { unmount } = renderPage();

      await submitSignupForm(
        {},
        {
          isSignUpComplete: true,
          nextStep: { signUpStep: 'DONE' },
        } as Awaited<ReturnType<typeof signUp>>,
      );

      unmount();

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      expect(mockNavigate).not.toHaveBeenCalled();
    });

    test('resets existing redirect timer when scheduling another redirect', async () => {
      renderPage();

      // Trigger first scheduled redirect via DONE step
      await submitSignupForm(
        {},
        {
          isSignUpComplete: true,
          nextStep: { signUpStep: 'DONE' },
        } as Awaited<ReturnType<typeof signUp>>,
      );

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Create Account' })).toBeInTheDocument();
      });

      // Advance partially
      act(() => {
        vi.advanceTimersByTime(1000);
      });

      // Submit again to trigger a second scheduleRedirect
      fillSignupForm();
      submitForm('Create Account');
      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Create Account' })).toBeInTheDocument();
      });

      // Advance 1000ms (total 2000ms from start, but only 1000ms from 2nd trigger)
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      // Should not have navigated yet because timer was reset to 1500ms
      expect(mockNavigate).not.toHaveBeenCalled();

      // Advance remaining 500ms
      act(() => {
        vi.advanceTimersByTime(500);
      });
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });
});
