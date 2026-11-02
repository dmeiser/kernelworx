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

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: false, loginWithPassword: vi.fn() }),
}));

describe('LoginPage google', () => {
  it('covers google login', async () => {
    const user = userEvent.setup();
    vi.mocked(amplifyAuth.signInWithRedirect).mockResolvedValue(undefined as any);
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: /continue with google/i }));
  });
});
