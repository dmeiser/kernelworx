import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MfaSetupRequiredState } from '../src/components/MfaSetupRequiredState';
import * as amplifyAuth from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  setUpTOTP: vi.fn(),
  verifyTOTPSetup: vi.fn(),
  updateMFAPreference: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,mockqrcode'),
  },
}));

describe('MfaSetupRequiredState', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    /* cspell:disable */
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: {
        idToken: {
          payload: {
            email: 'native@example.com',
          },
        },
      },
    } as any);
    vi.mocked(amplifyAuth.setUpTOTP).mockResolvedValue({
      sharedSecret: 'MOCKSECRET',
      getSetupUri: vi.fn(() => new URL('otpauth://totp/KernelWorx:admin?secret=MOCKSECRET')),
    } as any);
    /* cspell:enable */
    vi.mocked(amplifyAuth.signOut).mockResolvedValue(undefined as any);
  });

  describe('native user degradation flow', () => {
    it('renders the MFA Setup Required message and action button', () => {
      render(<MfaSetupRequiredState isFederated={false} />);

      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
      expect(screen.getByText('MFA Setup Required')).toBeInTheDocument();
      expect(screen.getByText(/Administrator Security Policy/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Set Up MFA/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Sign Out/i })).not.toBeInTheDocument();
    });

    it('opens setup dialog when Set Up MFA button is clicked', async () => {
      const user = userEvent.setup();
      render(<MfaSetupRequiredState isFederated={false} />);

      const button = screen.getByRole('button', { name: /Set Up MFA/i });
      await user.click(button);

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Set Up Multi-Factor Authentication/i })).toBeInTheDocument();
      });
    });

    it('automatically opens setup dialog when autoOpenDialog is true', async () => {
      render(<MfaSetupRequiredState autoOpenDialog={true} isFederated={false} />);

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Set Up Multi-Factor Authentication/i })).toBeInTheDocument();
      });
    });
  });

  describe('federated user degradation flow', () => {
    it('detects federated session and renders password sign-in state with no Set Up MFA button', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
        tokens: {
          idToken: {
            payload: {
              identities: [{ providerName: 'Google' }],
            },
          },
        },
      } as any);

      render(<MfaSetupRequiredState />);

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Admin access requires a password sign-in/i })).toBeInTheDocument();
      });

      expect(screen.getByText(/social provider which cannot present MFA/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Sign Out/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Back/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Set Up MFA/i })).not.toBeInTheDocument();
    });

    it('renders password sign-in state when isFederated is explicitly true', () => {
      render(<MfaSetupRequiredState isFederated={true} />);

      expect(screen.getByRole('heading', { name: /Admin access requires a password sign-in/i })).toBeInTheDocument();
      expect(screen.getByText(/social provider which cannot present MFA/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Sign Out/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Back/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Set Up MFA/i })).not.toBeInTheDocument();
    });

    it('opens password-sign-in dialog without TOTP setup when autoOpenDialog is true', async () => {
      render(<MfaSetupRequiredState autoOpenDialog={true} isFederated={true} />);

      await waitFor(() => {
        expect(screen.getAllByRole('heading', { name: /Admin access requires a password sign-in/i }).length).toBeGreaterThan(0);
      });

      // Does not show TOTP setup
      expect(amplifyAuth.setUpTOTP).not.toHaveBeenCalled();
      expect(screen.queryByLabelText(/Verification Code/i)).not.toBeInTheDocument();
    });

    it('handles Sign Out button click for federated user', async () => {
      const user = userEvent.setup();
      render(<MfaSetupRequiredState isFederated={true} />);

      const signOutButton = screen.getByRole('button', { name: /Sign Out/i });
      await user.click(signOutButton);

      await waitFor(() => {
        expect(amplifyAuth.signOut).toHaveBeenCalled();
      });
    });

    it('handles Back button click for federated user', async () => {
      const user = userEvent.setup();
      const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {});
      Object.defineProperty(window.history, 'length', { value: 2, writable: true });

      render(<MfaSetupRequiredState isFederated={true} />);

      const backButton = screen.getByRole('button', { name: /Back/i });
      await user.click(backButton);

      expect(backSpy).toHaveBeenCalled();
      backSpy.mockRestore();
    });
  });
});
