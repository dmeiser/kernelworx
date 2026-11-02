import { describe, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LoginPage } from '../src/pages/LoginPage';
import * as amplifyAuth from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
  signIn: vi.fn(),
  confirmSignIn: vi.fn(),
  signInWithRedirect: vi.fn(),
}));

const loginWithPassword = vi.fn().mockResolvedValue({ isSignedIn: true });

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: false, loginWithPassword }),
}));

describe('LoginPage ui', () => {
  it('covers ui interactions', async () => {
    const user = userEvent.setup();
    loginWithPassword.mockResolvedValue({ isSignedIn: false, nextStep: { signInStep: "CONFIRM_SIGN_IN_WITH_TOTP_CODE" } });
    vi.mocked(amplifyAuth.signInWithRedirect).mockResolvedValue(undefined as any);
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole('button', { name: /sign up/i }));
    await user.click(screen.getByRole('button', { name: /forgot password/i }));
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /^sign in$/i }));
  });
});

describe('LoginPage mfa ui', () => {
  it('covers mfa form', async () => {
    const user = userEvent.setup();
    loginWithPassword.mockResolvedValue({ isSignedIn: false, nextStep: { signInStep: 'CONFIRM_SIGN_IN_WITH_TOTP_CODE' } });
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText(/email/i), 'a@b.com');
    await user.type(screen.getByLabelText(/password/i), 'pw');
    await user.click(screen.getByRole('button', { name: /^sign in$/i }));
    // now mfa
    await user.type(screen.getByLabelText(/mfa code/i), '123456');
    await user.click(screen.getByRole('button', { name: /verify/i }));
  });
});
