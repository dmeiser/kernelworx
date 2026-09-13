import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MfaSetupRequiredState } from '../src/components/MfaSetupRequiredState';
import * as amplifyAuth from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
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
    vi.mocked(amplifyAuth.setUpTOTP).mockResolvedValue({
      sharedSecret: 'MOCKSECRET',
      getSetupUri: vi.fn(() => new URL('otpauth://totp/KernelWorx:admin?secret=MOCKSECRET')),
    } as any);
  });

  it('renders the MFA Setup Required message and action button', () => {
    render(<MfaSetupRequiredState />);

    expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
    expect(screen.getByText('MFA Setup Required')).toBeInTheDocument();
    expect(screen.getByText(/Administrator Security Policy/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Set Up MFA/i })).toBeInTheDocument();
  });

  it('opens dialog when Set Up MFA button is clicked', async () => {
    const user = userEvent.setup();
    render(<MfaSetupRequiredState />);

    const button = screen.getByRole('button', { name: /Set Up MFA/i });
    await user.click(button);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Set Up Multi-Factor Authentication/i })).toBeInTheDocument();
    });
  });

  it('automatically opens dialog when autoOpenDialog is true', async () => {
    render(<MfaSetupRequiredState autoOpenDialog={true} />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Set Up Multi-Factor Authentication/i })).toBeInTheDocument();
    });
  });
});
