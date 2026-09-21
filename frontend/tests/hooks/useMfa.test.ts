/**
 * Tests for useMfa hook
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import * as amplifyAuth from 'aws-amplify/auth';
import QRCode from 'qrcode';
import { useMfa } from '../../src/hooks/useMfa';
import { getMfaEnabledFromCognito } from '../../src/lib/mfaStatus';

vi.mock('aws-amplify/auth', () => ({
  setUpTOTP: vi.fn(),
  verifyTOTPSetup: vi.fn(),
  updateMFAPreference: vi.fn(),
  fetchMFAPreference: vi.fn(),
  deleteWebAuthnCredential: vi.fn(),
}));

vi.mock('../../src/lib/mfaStatus', () => ({
  getMfaEnabledFromCognito: vi.fn(),
}));

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn(),
  },
}));

/* cspell:disable */
const mockSharedSecret = 'JBSWY3DPEHPK3PXP';
const mockQrDataUrl = 'data:image/png;base64,mockqrcode';

describe('useMfa', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(amplifyAuth.setUpTOTP).mockResolvedValue({
      sharedSecret: mockSharedSecret,
      getSetupUri: vi.fn(() => new URL('otpauth://totp/PopcornManager:user?secret=JBSWY3DPEHPK3PXP')),
    } as any);
    (vi.mocked(QRCode.toDataURL) as any).mockResolvedValue(mockQrDataUrl);
    vi.mocked(amplifyAuth.verifyTOTPSetup).mockResolvedValue(undefined as any);
    vi.mocked(amplifyAuth.updateMFAPreference).mockResolvedValue(undefined as any);
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ preferred: 'TOTP' } as any);
  });
  /* cspell:enable */

  it('initializes with default values', () => {
    const { result } = renderHook(() => useMfa());
    expect(result.current.mfaSetupCode).toBeNull();
    expect(result.current.qrCodeUrl).toBeNull();
    expect(result.current.mfaVerificationCode).toBe('');
    expect(result.current.mfaError).toBeNull();
    expect(result.current.mfaSuccess).toBe(false);
    expect(result.current.mfaLoading).toBe(false);
    expect(result.current.mfaEnabled).toBe(false);
    expect(result.current.pendingConfirmation).toBeNull();
  });

  it('checks MFA status from the raw Cognito read and updates mfaEnabled', async () => {
    vi.mocked(getMfaEnabledFromCognito).mockResolvedValue(true);
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.checkMfaStatus();
    });

    // TOTP-only user: the raw read is the gate, Amplify is not consulted.
    expect(getMfaEnabledFromCognito).toHaveBeenCalledTimes(1);
    expect(amplifyAuth.fetchMFAPreference).not.toHaveBeenCalled();
    expect(result.current.mfaEnabled).toBe(true);

    vi.mocked(getMfaEnabledFromCognito).mockResolvedValue(false);
    await act(async () => {
      await result.current.checkMfaStatus();
    });
    expect(result.current.mfaEnabled).toBe(false);
  });

  it('treats a passkey-MFA-preferred user as MFA-enabled', async () => {
    // PreferredMfaSetting WEB_AUTHN_MFA: the pinned aws-amplify
    // fetchMFAPreference reads this user back as "no MFA", but the raw
    // GetUser read reports the enabled WEB_AUTHN_MFA setting.
    vi.mocked(getMfaEnabledFromCognito).mockResolvedValue(true);
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ preferred: undefined } as any);
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.checkMfaStatus();
    });

    expect(result.current.mfaEnabled).toBe(true);
  });

  it('falls back to fetchMFAPreference when the direct read fails', async () => {
    vi.mocked(getMfaEnabledFromCognito).mockRejectedValue(new Error('network'));
    const { result } = renderHook(() => useMfa());

    // beforeEach default: fetchMFAPreference -> { preferred: 'TOTP' }
    await act(async () => {
      await result.current.checkMfaStatus();
    });

    expect(amplifyAuth.fetchMFAPreference).toHaveBeenCalledTimes(1);
    expect(result.current.mfaEnabled).toBe(true);

    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ preferred: undefined } as any);
    await act(async () => {
      await result.current.checkMfaStatus();
    });
    expect(result.current.mfaEnabled).toBe(false);
  });

  it('leaves mfaEnabled false when both the direct read and the fallback fail', async () => {
    vi.mocked(getMfaEnabledFromCognito).mockRejectedValue(new Error('network'));
    vi.mocked(amplifyAuth.fetchMFAPreference).mockRejectedValue(new Error('no session'));
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.checkMfaStatus();
    });

    expect(result.current.mfaEnabled).toBe(false);
  });

  it('sets up TOTP MFA directly without deleting passkeys (coexistence)', async () => {
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.handleSetupMFA();
    });

    expect(amplifyAuth.setUpTOTP).toHaveBeenCalledTimes(1);
    expect(QRCode.toDataURL).toHaveBeenCalled();
    // Crucial two-path MFA assertion: deleteWebAuthnCredential is NEVER called
    expect(amplifyAuth.deleteWebAuthnCredential).not.toHaveBeenCalled();
    // No confirmation dialog prompting to delete passkeys
    expect(result.current.pendingConfirmation).toBeNull();
    expect(result.current.mfaSetupCode).toBe(mockSharedSecret);
    expect(result.current.qrCodeUrl).toBe(mockQrDataUrl);
  });

  it('verifies TOTP and updates preference to PREFERRED', async () => {
    const { result } = renderHook(() => useMfa());

    act(() => {
      result.current.setMfaVerificationCode('123456');
    });

    const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent;
    await act(async () => {
      await result.current.handleVerifyMFA(mockEvent);
    });

    expect(amplifyAuth.verifyTOTPSetup).toHaveBeenCalledWith({ code: '123456' });
    expect(amplifyAuth.updateMFAPreference).toHaveBeenCalledWith({ totp: 'PREFERRED' });
    expect(result.current.mfaSuccess).toBe(true);
    expect(result.current.mfaEnabled).toBe(true);
    expect(result.current.mfaVerificationCode).toBe('');
    expect(result.current.mfaSetupCode).toBeNull();
  });

  it('handles verification failure with error', async () => {
    vi.mocked(amplifyAuth.verifyTOTPSetup).mockRejectedValue(new Error('Invalid code'));
    const { result } = renderHook(() => useMfa());

    act(() => {
      result.current.setMfaVerificationCode('000000');
    });

    const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent;
    await act(async () => {
      await result.current.handleVerifyMFA(mockEvent);
    });

    expect(result.current.mfaError).toBe('Invalid code');
    expect(result.current.mfaSuccess).toBe(false);
  });

  it('handles disable MFA confirmation flow', async () => {
    const { result } = renderHook(() => useMfa());

    act(() => {
      result.current.handleDisableMFA();
    });

    expect(result.current.pendingConfirmation).toEqual({
      type: 'disable',
      message: 'Are you sure you want to disable multi-factor authentication? This will make your account less secure.',
    });

    await act(async () => {
      await result.current.confirmDisableMFA();
    });

    expect(amplifyAuth.updateMFAPreference).toHaveBeenCalledWith({ totp: 'DISABLED' });
    expect(result.current.mfaEnabled).toBe(false);
    expect(result.current.pendingConfirmation).toBeNull();
  });

  it('cancels disable MFA confirmation without disabling', () => {
    const { result } = renderHook(() => useMfa());

    act(() => {
      result.current.handleDisableMFA();
    });
    expect(result.current.pendingConfirmation).not.toBeNull();

    act(() => {
      result.current.cancelMfaConfirmation();
    });
    expect(result.current.pendingConfirmation).toBeNull();
    expect(amplifyAuth.updateMFAPreference).not.toHaveBeenCalled();
  });

  it('resets MFA setup state', () => {
    const { result } = renderHook(() => useMfa());

    act(() => {
      result.current.setMfaVerificationCode('123456');
    });
    expect(result.current.mfaVerificationCode).toBe('123456');

    act(() => {
      result.current.resetMfaSetup();
    });
    expect(result.current.mfaVerificationCode).toBe('');
    expect(result.current.mfaSetupCode).toBeNull();
    expect(result.current.qrCodeUrl).toBeNull();
  });
});

describe('useMfa error paths and confirmSetupMFA', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(amplifyAuth.setUpTOTP).mockResolvedValue({
      sharedSecret: mockSharedSecret,
      getSetupUri: vi.fn(() => new URL('otpauth://totp/PopcornManager:user?secret=JBSWY3DPEHPK3PXP')),
    } as any);
    (vi.mocked(QRCode.toDataURL) as any).mockResolvedValue(mockQrDataUrl);
    vi.mocked(amplifyAuth.verifyTOTPSetup).mockResolvedValue(undefined as any);
    vi.mocked(amplifyAuth.updateMFAPreference).mockResolvedValue(undefined as any);
    vi.mocked(amplifyAuth.fetchMFAPreference).mockResolvedValue({ preferred: 'TOTP' } as any);
  });

  it('regenerates the TOTP setup via confirmSetupMFA and clears prior errors', async () => {
    const { result } = renderHook(() => useMfa());

    act(() => {
      result.current.setMfaError('stale error');
      result.current.handleDisableMFA();
    });

    await act(async () => {
      await result.current.confirmSetupMFA();
    });

    expect(result.current.mfaError).toBeNull();
    expect(result.current.mfaSetupCode).toBe(mockSharedSecret);
    expect(result.current.qrCodeUrl).toBe(mockQrDataUrl);
    expect(result.current.pendingConfirmation).toBeNull();
  });

  it('surfaces the object error message when setup fails with a non-Error object', async () => {
    vi.mocked(amplifyAuth.setUpTOTP).mockRejectedValue({ message: 'totp exploded' } as any);
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.confirmSetupMFA();
    });

    expect(result.current.mfaError).toBe('totp exploded');
  });

  it('falls back to the static message when setup fails with a non-object error', async () => {
    vi.mocked(amplifyAuth.setUpTOTP).mockRejectedValue('totp-string' as any);
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.handleSetupMFA();
    });

    expect(result.current.mfaError).toBe('Failed to set up MFA');
  });

  it('uses the verification fallback message for non-Error, non-object failures', async () => {
    vi.mocked(amplifyAuth.verifyTOTPSetup).mockRejectedValue('verify-string' as any);
    const { result } = renderHook(() => useMfa());

    const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent;
    await act(async () => {
      await result.current.handleVerifyMFA(mockEvent);
    });

    expect(result.current.mfaError).toBe('Invalid verification code. Please try again.');
  });

  it('surfaces the object message when verification fails with a non-Error object', async () => {
    vi.mocked(amplifyAuth.verifyTOTPSetup).mockRejectedValue({ message: 'code rejected' } as any);
    const { result } = renderHook(() => useMfa());

    const mockEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent;
    await act(async () => {
      await result.current.handleVerifyMFA(mockEvent);
    });

    expect(result.current.mfaError).toBe('code rejected');
  });

  it('captures the error message when disabling MFA fails with a non-Error object', async () => {
    vi.mocked(amplifyAuth.updateMFAPreference).mockRejectedValue({ message: 'disable exploded' } as any);
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.confirmDisableMFA();
    });

    expect(result.current.mfaError).toBe('disable exploded');
    expect(result.current.mfaLoading).toBe(false);
  });

  it('falls back to the static message when disabling MFA fails with a primitive', async () => {
    vi.mocked(amplifyAuth.updateMFAPreference).mockRejectedValue('disable-string' as any);
    const { result } = renderHook(() => useMfa());

    await act(async () => {
      await result.current.confirmDisableMFA();
    });

    expect(result.current.mfaError).toBe('Failed to disable MFA');
  });
});
