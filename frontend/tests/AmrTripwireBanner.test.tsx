/**
 * AmrTripwireBanner component tests
 *
 * Tests the admin-only AMR tripwire banner behavior:
 * - admin + amr present -> banner renders
 * - admin without amr -> no banner
 * - non-admin with amr -> no banner
 * - dismissal per-session & reappearance on next sign-in
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as amplifyAuth from 'aws-amplify/auth';
import { AmrTripwireBanner } from '../src/components/AmrTripwireBanner';
import {
  isAdminUser,
  hasAmrClaim,
  shouldShowAmrBanner,
  getSessionDismissKey,
  getActiveTripwireKey,
  resolveActiveKeyFromSession,
} from '../src/lib/amrTripwire';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
}));

const mockSession = (payload?: Record<string, unknown>) => {
  if (!payload) {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: undefined,
    } as any);
    return;
  }
  vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
    tokens: {
      idToken: {
        payload,
        toString: () => 'mock-token',
      },
    },
  } as any);
};

describe('AmrTripwireBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  describe('Banner rendering gates', () => {
    it('renders banner when user is admin and amr claim is present', async () => {
      mockSession({
        'cognito:groups': ['ADMIN'],
        amr: ['pwd', 'mfa'],
        auth_time: 1700000000,
      });

      render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(screen.getByTestId('amr-tripwire-banner')).toBeInTheDocument();
      });

      expect(
        screen.getByText(
          'Cognito token behavior changed: a native amr claim appeared in your token. Report this to operations — the MFA claim injection may be retireable.',
        ),
      ).toBeInTheDocument();
    });

    it('does not render banner when user is admin but amr claim is absent', async () => {
      mockSession({
        'cognito:groups': ['ADMIN'],
        auth_time: 1700000000,
      });

      render(<AmrTripwireBanner />);

      // Wait for session check to complete
      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();
    });

    it('does not render banner when amr is present but user is not admin', async () => {
      mockSession({
        'cognito:groups': ['USER'],
        amr: ['pwd'],
        auth_time: 1700000000,
      });

      render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();
    });

    it('does not render banner when user is non-admin with no groups and amr is present', async () => {
      mockSession({
        amr: ['pwd'],
        auth_time: 1700000000,
      });

      render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();
    });

    it('does not render banner when neither admin nor amr is present', async () => {
      mockSession({
        'cognito:groups': ['USER'],
      });

      render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();
    });

    it('does not render banner when there is no active session', async () => {
      mockSession(undefined);

      render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();
    });

    it('handles fetchAuthSession rejection gracefully without rendering banner', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockRejectedValue(new Error('Auth failed'));

      render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();
    });
  });

  describe('Dismissal lifecycle', () => {
    it('can be dismissed for current session and reappears on next sign-in', async () => {
      const user = userEvent.setup();

      // Session 1: initial sign-in
      mockSession({
        'cognito:groups': ['ADMIN'],
        amr: ['mfa'],
        auth_time: 1000,
      });

      const { unmount } = render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(screen.getByTestId('amr-tripwire-banner')).toBeInTheDocument();
      });

      // Dismiss banner by clicking the close button
      const closeButton = screen.getByRole('button', { name: /close/i });
      await user.click(closeButton);

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();

      unmount();

      // Same session re-render: banner stays dismissed
      const { unmount: unmount2 } = render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });

      expect(screen.queryByTestId('amr-tripwire-banner')).not.toBeInTheDocument();

      unmount2();

      // Session 2: next sign-in (different auth_time)
      mockSession({
        'cognito:groups': ['ADMIN'],
        amr: ['mfa'],
        auth_time: 2000,
      });

      render(<AmrTripwireBanner />);

      await waitFor(() => {
        expect(screen.getByTestId('amr-tripwire-banner')).toBeInTheDocument();
      });
    });
  });

  describe('Helper functions', () => {
    it('isAdminUser identifies admin group in array or string', () => {
      expect(isAdminUser(undefined)).toBe(false);
      expect(isAdminUser({})).toBe(false);
      expect(isAdminUser({ 'cognito:groups': ['ADMIN'] })).toBe(true);
      expect(isAdminUser({ 'cognito:groups': ['USER', 'ADMIN'] })).toBe(true);
      expect(isAdminUser({ 'cognito:groups': 'ADMIN' })).toBe(true);
      expect(isAdminUser({ 'cognito:groups': ['USER'] })).toBe(false);
      expect(isAdminUser({ 'cognito:groups': 'USER' })).toBe(false);
    });

    it('hasAmrClaim detects presence of amr claim regardless of value', () => {
      expect(hasAmrClaim(undefined)).toBe(false);
      expect(hasAmrClaim({})).toBe(false);
      expect(hasAmrClaim({ amr: ['pwd'] })).toBe(true);
      expect(hasAmrClaim({ amr: [] })).toBe(true);
      expect(hasAmrClaim({ amr: 'mfa' })).toBe(true);
      expect(hasAmrClaim({ amr: null })).toBe(true);
      expect(hasAmrClaim({ amr: false })).toBe(true);
      expect(hasAmrClaim({ other: 'value' })).toBe(false);
    });

    it('shouldShowAmrBanner requires both admin status and amr claim', () => {
      expect(shouldShowAmrBanner({ 'cognito:groups': ['ADMIN'], amr: ['pwd'] })).toBe(true);
      expect(shouldShowAmrBanner({ 'cognito:groups': ['ADMIN'] })).toBe(false);
      expect(shouldShowAmrBanner({ 'cognito:groups': ['USER'], amr: ['pwd'] })).toBe(false);
      expect(shouldShowAmrBanner(undefined)).toBe(false);
    });

    it('getSessionDismissKey uses jti or auth_time', () => {
      expect(getSessionDismissKey({ jti: 'jwt-123' })).toBe('amr_tripwire_dismissed_jwt-123');
      expect(getSessionDismissKey({ auth_time: 12345 })).toBe('amr_tripwire_dismissed_12345');
      expect(getSessionDismissKey({})).toBe('amr_tripwire_dismissed');
      expect(getSessionDismissKey(undefined)).toBe('amr_tripwire_dismissed');
    });

    it('getActiveTripwireKey returns key only when eligible and not dismissed', () => {
      const payload = { 'cognito:groups': ['ADMIN'], amr: ['pwd'], auth_time: 12345 };
      expect(getActiveTripwireKey(payload)).toBe('amr_tripwire_dismissed_12345');
      sessionStorage.setItem('amr_tripwire_dismissed_12345', 'true');
      expect(getActiveTripwireKey(payload)).toBeNull();
      expect(getActiveTripwireKey({ 'cognito:groups': ['USER'], amr: ['pwd'] })).toBeNull();
    });

    it('resolveActiveKeyFromSession extracts payload from session', () => {
      const session = {
        tokens: {
          idToken: {
            payload: { 'cognito:groups': ['ADMIN'], amr: ['pwd'], jti: 'jti-abc' },
          },
        },
      };
      expect(resolveActiveKeyFromSession(session)).toBe('amr_tripwire_dismissed_jti-abc');
      expect(resolveActiveKeyFromSession(undefined)).toBeNull();
    });
  });
});
