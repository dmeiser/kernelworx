import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MfaSetupDialog } from '../src/components/MfaSetupDialog';
import * as amplifyAuth from 'aws-amplify/auth';
import QRCode from 'qrcode';

// Mock Amplify Auth
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  setUpTOTP: vi.fn(),
  verifyTOTPSetup: vi.fn(),
  updateMFAPreference: vi.fn(),
  signOut: vi.fn(),
}));

// Mock QRCode
vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn(),
  },
}));

describe('MfaSetupDialog', () => {
  /* cspell:disable */
  const mockSharedSecret = 'JBSWY3DPEHPK3PXP';
  const mockOtpauthUrl = 'otpauth://totp/KernelWorx:admin@example.com?secret=JBSWY3DPEHPK3PXP&issuer=KernelWorx';
  const mockQrDataUrl = 'data:image/png;base64,mockqrcode';
  /* cspell:enable */

  beforeEach(() => {
    vi.clearAllMocks();
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
      sharedSecret: mockSharedSecret,
      getSetupUri: vi.fn(() => new URL(mockOtpauthUrl)),
    } as any);
    (vi.mocked(QRCode.toDataURL) as any).mockResolvedValue(mockQrDataUrl);
    vi.mocked(amplifyAuth.verifyTOTPSetup).mockResolvedValue(undefined as any);
    vi.mocked(amplifyAuth.updateMFAPreference).mockResolvedValue(undefined as any);
    vi.mocked(amplifyAuth.signOut).mockResolvedValue(undefined as any);
  });

  it('does not render when open is false', () => {
    render(<MfaSetupDialog open={false} onClose={vi.fn()} />);
    expect(screen.queryByText(/Set Up Multi-Factor Authentication/i)).not.toBeInTheDocument();
  });

  it('calls setUpTOTP and displays secret, otpauth URL, and QR code for native user', async () => {
    render(<MfaSetupDialog open={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(mockSharedSecret)).toBeInTheDocument();
    });

    expect(amplifyAuth.setUpTOTP).toHaveBeenCalled();
    expect(screen.getByText(mockOtpauthUrl)).toBeInTheDocument();
    const qrImg = screen.getByAltText('MFA QR Code');
    expect(qrImg).toBeInTheDocument();
    expect(qrImg).toHaveAttribute('src', mockQrDataUrl);
  });

  it('displays error if setUpTOTP fails for native user', async () => {
    vi.mocked(amplifyAuth.setUpTOTP).mockRejectedValue(new Error('Cognito network error'));

    render(<MfaSetupDialog open={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Cognito network error')).toBeInTheDocument();
    });
  });

  it('verifies code, enables preferred MFA, shows "MFA enabled — sign in again", and signs out', async () => {
    const user = userEvent.setup();
    const handleSuccess = vi.fn();

    render(<MfaSetupDialog open={true} onClose={vi.fn()} onSuccess={handleSuccess} />);

    // Wait for setup details to load
    await waitFor(() => {
      expect(screen.getByText(mockSharedSecret)).toBeInTheDocument();
    });

    const input = screen.getByLabelText(/Verification Code/i);
    const verifyButton = screen.getByRole('button', { name: /Verify & Enable/i });

    // Verify button should be disabled when code length is not 6
    expect(verifyButton).toBeDisabled();

    await user.type(input, '123456');
    expect(verifyButton).toBeEnabled();

    await user.click(verifyButton);

    await waitFor(() => {
      expect(amplifyAuth.verifyTOTPSetup).toHaveBeenCalledWith({ code: '123456' });
      expect(amplifyAuth.updateMFAPreference).toHaveBeenCalledWith({ totp: 'PREFERRED' });
      expect(amplifyAuth.signOut).toHaveBeenCalled();
    });

    // Requirement: show 'MFA enabled — sign in again' and sign the user out
    expect(screen.getByText(/MFA enabled — sign in again/i)).toBeInTheDocument();
    expect(handleSuccess).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /Sign In Again/i })).toBeInTheDocument();
  });

  it('shows error when verification fails', async () => {
    const user = userEvent.setup();
    vi.mocked(amplifyAuth.verifyTOTPSetup).mockRejectedValue(new Error('Invalid code'));

    render(<MfaSetupDialog open={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(mockSharedSecret)).toBeInTheDocument();
    });

    const input = screen.getByLabelText(/Verification Code/i);
    await user.type(input, '000000');

    const verifyButton = screen.getByRole('button', { name: /Verify & Enable/i });
    await user.click(verifyButton);

    await waitFor(() => {
      expect(screen.getByText('Invalid code')).toBeInTheDocument();
    });

    // Sign out should not have been called
    expect(amplifyAuth.signOut).not.toHaveBeenCalled();
    // Success message should not appear
    expect(screen.queryByText(/MFA enabled — sign in again/i)).not.toBeInTheDocument();
  });

  it('allows cancelling when not yet verified', async () => {
    const user = userEvent.setup();
    const handleClose = vi.fn();

    render(<MfaSetupDialog open={true} onClose={handleClose} />);

    await waitFor(() => {
      expect(screen.getByText(mockSharedSecret)).toBeInTheDocument();
    });

    const cancelButton = screen.getByRole('button', { name: /Cancel/i });
    await user.click(cancelButton);

    expect(handleClose).toHaveBeenCalled();
  });

  describe('federated session handling', () => {
    it('detects federated session from token and renders password-sign-in dialog with no TOTP setup', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
        tokens: {
          idToken: {
            payload: {
              identities: [{ providerName: 'Google' }],
            },
          },
        },
      } as any);

      render(<MfaSetupDialog open={true} onClose={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Admin access requires a password sign-in/i })).toBeInTheDocument();
      });

      expect(screen.getByText(/social provider which cannot present MFA/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Sign Out/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Back/i })).toBeInTheDocument();

      // Must NOT call setUpTOTP or render TOTP setup elements
      expect(amplifyAuth.setUpTOTP).not.toHaveBeenCalled();
      expect(screen.queryByLabelText(/Verification Code/i)).not.toBeInTheDocument();
      expect(screen.queryByAltText('MFA QR Code')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Verify & Enable/i })).not.toBeInTheDocument();
    });

    it('renders password-sign-in dialog when isFederated prop is explicitly true', async () => {
      render(<MfaSetupDialog open={true} onClose={vi.fn()} isFederated={true} />);

      expect(screen.getByRole('heading', { name: /Admin access requires a password sign-in/i })).toBeInTheDocument();
      expect(screen.getByText(/social provider which cannot present MFA/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Sign Out/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Back/i })).toBeInTheDocument();

      expect(amplifyAuth.setUpTOTP).not.toHaveBeenCalled();
    });

    it('calls signOut and redirects when Sign Out is clicked on federated dialog', async () => {
      const user = userEvent.setup();
      render(<MfaSetupDialog open={true} onClose={vi.fn()} isFederated={true} />);

      const signOutButton = screen.getByRole('button', { name: /Sign Out/i });
      await user.click(signOutButton);

      await waitFor(() => {
        expect(amplifyAuth.signOut).toHaveBeenCalled();
      });
    });

    it('calls onClose when Back is clicked on federated dialog', async () => {
      const user = userEvent.setup();
      const handleClose = vi.fn();
      render(<MfaSetupDialog open={true} onClose={handleClose} isFederated={true} />);

      const backButton = screen.getByRole('button', { name: /Back/i });
      await user.click(backButton);

      expect(handleClose).toHaveBeenCalled();
    });
  });

  describe('verification error variants', () => {
    const typeCodeAndVerify = async (user: ReturnType<typeof userEvent.setup>) => {
      const input = screen.getByLabelText(/Verification Code/i);
      await user.type(input, '654321');
      await user.click(screen.getByRole('button', { name: /Verify & Enable/i }));
    };

    it('surfaces the object message when verification fails with a non-Error object', async () => {
      const user = userEvent.setup();
      vi.mocked(amplifyAuth.verifyTOTPSetup).mockRejectedValue({ message: 'object code error' } as any);
      render(<MfaSetupDialog open={true} onClose={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(mockSharedSecret)).toBeInTheDocument();
      });
      await typeCodeAndVerify(user);

      await waitFor(() => {
        expect(screen.getByText('object code error')).toBeInTheDocument();
      });
      expect(amplifyAuth.signOut).not.toHaveBeenCalled();
    });

    it('falls back to the static message when verification fails with a primitive', async () => {
      const user = userEvent.setup();
      vi.mocked(amplifyAuth.verifyTOTPSetup).mockRejectedValue('primitive failure' as any);
      render(<MfaSetupDialog open={true} onClose={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(mockSharedSecret)).toBeInTheDocument();
      });
      await typeCodeAndVerify(user);

      await waitFor(() => {
        expect(screen.getByText(/Invalid verification code/i)).toBeInTheDocument();
      });
    });

    it('surfaces the preference update failure after a successful verify', async () => {
      const user = userEvent.setup();
      vi.mocked(amplifyAuth.updateMFAPreference).mockRejectedValue(new Error('preference update failed'));
      render(<MfaSetupDialog open={true} onClose={vi.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(mockSharedSecret)).toBeInTheDocument();
      });
      await typeCodeAndVerify(user);

      await waitFor(() => {
        expect(screen.getByText('preference update failed')).toBeInTheDocument();
      });
      expect(amplifyAuth.signOut).not.toHaveBeenCalled();
      expect(screen.queryByText(/MFA enabled — sign in again/i)).not.toBeInTheDocument();
    });
  });
});
