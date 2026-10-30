import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LoginPage } from '../src/pages/LoginPage';
import * as amplifyAuth from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
  signIn: vi.fn(),
  confirmSignIn: vi.fn(),
  signInWithRedirect: vi.fn(),
}));

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    loginWithPassword: vi.fn(),
  }),
}));

describe('LoginPage handleFirstFactorSelection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('clears loading state when confirmSignIn returns no next step', async () => {
    const user = userEvent.setup();
    vi.mocked(amplifyAuth.signIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: 'CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION' },
    } as any);
    vi.mocked(amplifyAuth.confirmSignIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: undefined },
    } as any);

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/email/i), 'test@example.com');
    await user.click(screen.getByRole('button', { name: /sign in with passkey/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign in with passkey/i })).not.toBeDisabled();
    });
  });

  it('routes a returned step through applyLoginAction', async () => {
    const user = userEvent.setup();
    vi.mocked(amplifyAuth.signIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: 'CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION' },
    } as any);
    vi.mocked(amplifyAuth.confirmSignIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: 'CONFIRM_SIGN_IN_WITH_TOTP_CODE' },
    } as any);

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/email/i), 'test@example.com');
    await user.click(screen.getByRole('button', { name: /sign in with passkey/i }));

    await waitFor(() => {
      expect(screen.getByLabelText(/mfa code/i)).toBeInTheDocument();
    });
  });

  it('falls through applyLoginAction when confirmSignIn returns first-factor-selection again', async () => {
    const user = userEvent.setup();
    vi.mocked(amplifyAuth.signIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: 'CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION' },
    } as any);
    vi.mocked(amplifyAuth.confirmSignIn).mockResolvedValue({
      isSignedIn: false,
      nextStep: { signInStep: 'CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION' },
    } as any);

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/email/i), 'test@example.com');
    await user.click(screen.getByRole('button', { name: /sign in with passkey/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign in with passkey/i })).not.toBeDisabled();
    });
  });
});

import { renderHook, act } from '@testing-library/react';
import { useLoginState } from '../src/pages/LoginPage';

describe('LoginPage useLoginState', () => {
  beforeEach(() => vi.clearAllMocks());

  it('covers email login success and failure', async () => {
    const navigate = vi.fn();
    const loginWithPassword = vi.fn().mockResolvedValue({ isSignedIn: true });
    const { result } = renderHook(() => useLoginState(loginWithPassword as any, navigate as any, '/home'));

    act(() => {
      result.current.setEmail('a@b.com');
      result.current.setPassword('pw');
    });

    const e = { preventDefault: vi.fn() } as any;
    await act(async () => {
      await result.current.handleEmailLogin(e);
    });
    expect(navigate).toHaveBeenCalledWith('/home', { replace: true });

    const err = new Error('bad');
    loginWithPassword.mockRejectedValueOnce(err);
    await act(async () => {
      await result.current.handleEmailLogin(e);
    });
    expect(result.current.error).toBe('bad');
    expect(result.current.loading).toBe(false);

    loginWithPassword.mockResolvedValueOnce({ isSignedIn: false, nextStep: { signInStep: 'CONFIRM_SIGN_IN_WITH_TOTP_CODE' } });
    await act(async () => {
      await result.current.handleEmailLogin(e);
    });
    expect(result.current.showMfa).toBe(true);

    loginWithPassword.mockResolvedValueOnce({ isSignedIn: false, nextStep: { signInStep: 'UNKNOWN_STEP' } });
    await act(async () => {
      await result.current.handleEmailLogin(e);
    });
    expect(result.current.error).toContain('Unexpected authentication step');
  });

  it('covers MFA submit success and failure', async () => {
    const navigate = vi.fn();
    const loginWithPassword = vi.fn();
    const { result } = renderHook(() => useLoginState(loginWithPassword as any, navigate as any, '/home'));

    vi.mocked(amplifyAuth.confirmSignIn).mockResolvedValueOnce({ isSignedIn: true } as any);
    act(() => result.current.setMfaCode('123456'));
    const e = { preventDefault: vi.fn() } as any;
    await act(async () => {
      await result.current.handleMfaSubmit(e);
    });
    expect(result.current.showMfa).toBe(false);

    vi.mocked(amplifyAuth.confirmSignIn).mockResolvedValueOnce({ isSignedIn: false } as any);
    act(() => result.current.setMfaCode('123456'));
    await act(async () => {
      await result.current.handleMfaSubmit(e);
    });
    expect(result.current.error).toBe('MFA verification failed');

    vi.mocked(amplifyAuth.confirmSignIn).mockRejectedValueOnce(new Error('bad mfa'));
    act(() => result.current.setMfaCode('123456'));
    await act(async () => {
      await result.current.handleMfaSubmit(e);
    });
    expect(result.current.error).toBe('bad mfa');
  });

  it('covers passkey login', async () => {
    const navigate = vi.fn();
    const loginWithPassword = vi.fn();
    const { result } = renderHook(() => useLoginState(loginWithPassword as any, navigate as any, '/home'));

    // no email
    await act(async () => {
      await result.current.handlePasskeyLogin();
    });
    expect(result.current.error).toBe('Please enter your email address');

    // signed in
    act(() => result.current.setEmail('a@b.com'));
    vi.mocked(amplifyAuth.signIn).mockResolvedValueOnce({ isSignedIn: true } as any);
    await act(async () => {
      await result.current.handlePasskeyLogin();
    });

    // with first factor selection
    vi.mocked(amplifyAuth.signIn).mockResolvedValueOnce({ isSignedIn: false, nextStep: { signInStep: 'CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION' } } as any);
    vi.mocked(amplifyAuth.confirmSignIn).mockResolvedValueOnce({ isSignedIn: true } as any);
    await act(async () => {
      await result.current.handlePasskeyLogin();
    });

    // error
    vi.mocked(amplifyAuth.signIn).mockRejectedValueOnce(new Error('passkey fail'));
    await act(async () => {
      await result.current.handlePasskeyLogin();
    });
    expect(result.current.error).toBe('passkey fail');
    expect(result.current.loading).toBe(false);
  });

  it('covers social login success and failure', async () => {
    const navigate = vi.fn();
    const loginWithPassword = vi.fn();
    const { result } = renderHook(() => useLoginState(loginWithPassword as any, navigate as any, '/dashboard'));

    vi.mocked(amplifyAuth.signInWithRedirect).mockResolvedValueOnce(undefined as any);
    await act(async () => {
      await result.current.handleSocialLogin('Google');
    });
    expect(sessionStorage.getItem('oauth_redirect')).toBe('/dashboard');

    act(() => result.current.setError(null));
    vi.mocked(amplifyAuth.signInWithRedirect).mockRejectedValueOnce(new Error('boom'));
    await act(async () => {
      await result.current.handleSocialLogin('Facebook');
    });
    expect(result.current.error).toBe('Facebook login failed. Please try again.');
    expect(result.current.loading).toBe(false);
  });

  it('covers handleBack and setters', () => {
    const navigate = vi.fn();
    const loginWithPassword = vi.fn();
    const { result } = renderHook(() => useLoginState(loginWithPassword as any, navigate as any, '/home'));
    act(() => {
      result.current.setMfaCode('1');
      result.current.setPassword('p');
      result.current.handleBack();
    });
    expect(result.current.showMfa).toBe(false);
  });
});

describe('LoginPage extra branches', () => {
  it('covers webauthn step and object error', async () => {
    const navigate = vi.fn();
    const loginWithPassword = vi.fn().mockResolvedValue({ isSignedIn: false, nextStep: { signInStep: 'CONFIRM_SIGN_IN_WITH_WEBAUTHN' } });
    const { result } = renderHook(() => useLoginState(loginWithPassword as any, navigate as any, '/home'));
    const e = { preventDefault: vi.fn() } as any;
    await act(async () => {
      await result.current.handleEmailLogin(e);
    });
    expect(result.current.showPasskeyPrompt).toBe(true);

    const objErr = { message: 'obj failure' };
    loginWithPassword.mockRejectedValueOnce(objErr);
    await act(async () => {
      await result.current.handleEmailLogin(e);
    });
    expect(result.current.error).toBe('obj failure');
  });
});
