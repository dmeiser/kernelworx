/**
 * AuthContext tests
 *
 * Regression test for the post-MFA login redirect bug (KW-ISSUE-336): a direct
 * sign-in (password + TOTP confirmSignIn, passkey, or first-factor selection)
 * completes by dispatching a `signedIn` auth event. The provider must react to
 * that event by re-checking the session so `isAuthenticated` flips to true.
 * Without the handler, the post-challenge redirect lands on a guarded route that
 * still sees the stale unauthenticated state and bounces the user back to /login.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Hub } from 'aws-amplify/utils';
import { fetchAuthSession, getCurrentUser } from 'aws-amplify/auth';
import type { AuthSession } from 'aws-amplify/auth';
import { apolloClient } from '../lib/apollo';
import { AuthProvider, useAuth } from './AuthContext';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  getCurrentUser: vi.fn(),
  signIn: vi.fn(),
  signInWithRedirect: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('../lib/apollo', () => ({
  apolloClient: { query: vi.fn() },
}));

const AuthProbe: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();
  return (
    <div>
      <span data-testid="auth">{String(isAuthenticated)}</span>
      <span data-testid="loading">{String(loading)}</span>
    </div>
  );
};

describe('AuthProvider signedIn auth event', () => {
  let sessionHasTokens: boolean;

  beforeEach(() => {
    sessionHasTokens = false;
    vi.mocked(fetchAuthSession).mockImplementation(async (): Promise<AuthSession> => {
      // Read the flag at call time so the mount-time check sees "no tokens" and
      // the signedIn-triggered check sees "tokens present".
      if (sessionHasTokens) {
        return { tokens: { idToken: { payload: {} } } } as unknown as AuthSession;
      }
      return {} as unknown as AuthSession;
    });
    vi.mocked(getCurrentUser).mockResolvedValue({ username: 'testuser', attributes: { sub: 'sub1' } } as never);
    vi.mocked(apolloClient.query).mockResolvedValue({ data: {} });
  });

  it('flips isAuthenticated to true when a signedIn auth event fires', async () => {
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    // Unauthenticated until a direct sign-in completes, and the initial mount
    // check has settled.
    await waitFor(() => expect(screen.getByTestId('auth')).toHaveTextContent('false'));
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));

    // Simulate a completed direct sign-in: tokens now exist and Amplify
    // dispatches the `signedIn` auth event.
    sessionHasTokens = true;
    Hub.dispatch('auth', { event: 'signedIn' }, 'Auth');

    await waitFor(() => expect(screen.getByTestId('auth')).toHaveTextContent('true'));
  });

  it('does not flip isAuthenticated for unrelated auth events', async () => {
    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));

    // An event with no registered handler must leave the (unauthenticated)
    // session untouched.
    Hub.dispatch('auth', { event: 'someUnrelatedEvent' }, 'Auth');

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByTestId('auth')).toHaveTextContent('false');
  });
});
