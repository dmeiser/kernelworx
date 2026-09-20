/**
 * Tests for usePasskeys hook
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import * as amplifyAuth from 'aws-amplify/auth';
import { usePasskeys } from '../../src/hooks/usePasskeys';
import { enablePasskeyMfa, PASSKEY_MFA_ENABLE_FAILED_MESSAGE } from '../../src/lib/passkeyMfa';

vi.mock('aws-amplify/auth', () => ({
  associateWebAuthnCredential: vi.fn(),
  listWebAuthnCredentials: vi.fn(),
  deleteWebAuthnCredential: vi.fn(),
  updateMFAPreference: vi.fn(),
}));

vi.mock('../../src/lib/passkeyMfa', () => ({
  enablePasskeyMfa: vi.fn(),
  PASSKEY_MFA_ENABLE_FAILED_MESSAGE: 'Passkey was registered, but passkey sign-in could not be enabled.',
}));

describe('usePasskeys', () => {
  const mockCredentials = [
    {
      credentialId: 'cred-123',
      friendlyCredentialName: 'My MacBook',
      relyingPartyId: 'kernelworx.app',
      createdAt: new Date('2026-01-01T00:00:00Z'),
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(amplifyAuth.listWebAuthnCredentials).mockResolvedValue({
      credentials: mockCredentials as any,
    });
    vi.mocked(amplifyAuth.associateWebAuthnCredential).mockResolvedValue(undefined as any);
    vi.mocked(amplifyAuth.deleteWebAuthnCredential).mockResolvedValue(undefined as any);
    vi.mocked(enablePasskeyMfa).mockResolvedValue(undefined);
  });

  it('initializes with empty defaults', () => {
    const { result } = renderHook(() => usePasskeys());
    expect(result.current.passkeys).toEqual([]);
    expect(result.current.passkeyName).toBe('');
    expect(result.current.passkeyError).toBeNull();
    expect(result.current.passkeySuccess).toBe(false);
    expect(result.current.passkeyLoading).toBe(false);
    expect(result.current.pendingConfirmation).toBeNull();
  });

  it('loads passkeys successfully', async () => {
    const { result } = renderHook(() => usePasskeys());

    await act(async () => {
      await result.current.loadPasskeys();
    });

    expect(amplifyAuth.listWebAuthnCredentials).toHaveBeenCalledTimes(1);
    expect(result.current.passkeys).toEqual(mockCredentials);
  });

  it('handles load passkeys failure gracefully without throwing', async () => {
    vi.mocked(amplifyAuth.listWebAuthnCredentials).mockRejectedValue(new Error('Network error'));
    const { result } = renderHook(() => usePasskeys());

    await act(async () => {
      await result.current.loadPasskeys();
    });

    expect(result.current.passkeys).toEqual([]);
  });

  it('requires a passkey name before registering', async () => {
    const { result } = renderHook(() => usePasskeys());

    await act(async () => {
      await result.current.handleRegisterPasskey();
    });

    expect(result.current.passkeyError).toBe('Please enter a name for this passkey');
    expect(amplifyAuth.associateWebAuthnCredential).not.toHaveBeenCalled();
  });

  it('registers passkey, enables passkey MFA, and leaves TOTP untouched (coexistence)', async () => {
    const { result } = renderHook(() => usePasskeys());

    act(() => {
      result.current.setPasskeyName('New Security Key');
    });

    await act(async () => {
      await result.current.handleRegisterPasskey();
    });

    expect(amplifyAuth.associateWebAuthnCredential).toHaveBeenCalledTimes(1);
    // Per-user "User verification with passkey" MFA must be enabled the
    // same way the Cognito console toggle does (SetUserMFAPreference)
    expect(enablePasskeyMfa).toHaveBeenCalledTimes(1);
    // Crucial two-path MFA assertion: updateMFAPreference is NEVER called to disable TOTP
    expect(amplifyAuth.updateMFAPreference).not.toHaveBeenCalled();
    // No confirmation dialog needed
    expect(result.current.pendingConfirmation).toBeNull();
    expect(result.current.passkeySuccess).toBe(true);
    expect(result.current.passkeyName).toBe('');
    expect(amplifyAuth.listWebAuthnCredentials).toHaveBeenCalled();
  });

  it('does not enable passkey MFA when registration fails', async () => {
    vi.mocked(amplifyAuth.associateWebAuthnCredential).mockRejectedValue(new Error('Passkey rejected'));
    const { result } = renderHook(() => usePasskeys());

    act(() => {
      result.current.setPasskeyName('Phone');
    });

    await act(async () => {
      await result.current.handleRegisterPasskey();
    });

    expect(enablePasskeyMfa).not.toHaveBeenCalled();
    expect(result.current.passkeyError).toBe('Passkey rejected');
    expect(result.current.passkeySuccess).toBe(false);
  });

  it('reports an error but keeps the credential when passkey MFA enablement fails', async () => {
    vi.mocked(enablePasskeyMfa).mockRejectedValue(new Error('WebAuthn MFA not enabled on pool'));
    const { result } = renderHook(() => usePasskeys());

    act(() => {
      result.current.setPasskeyName('Phone');
    });

    await act(async () => {
      await result.current.handleRegisterPasskey();
    });

    expect(amplifyAuth.associateWebAuthnCredential).toHaveBeenCalledTimes(1);
    expect(enablePasskeyMfa).toHaveBeenCalledTimes(1);
    expect(result.current.passkeySuccess).toBe(false);
    expect(result.current.passkeyError).toBe(PASSKEY_MFA_ENABLE_FAILED_MESSAGE);
    // The registered credential is still listed for the user to see
    expect(amplifyAuth.listWebAuthnCredentials).toHaveBeenCalled();
  });

  it('handles deleting a passkey with confirmation flow', async () => {
    const { result } = renderHook(() => usePasskeys());

    act(() => {
      result.current.handleDeletePasskey('cred-123');
    });

    expect(result.current.pendingConfirmation).toEqual({
      type: 'delete',
      message: 'Are you sure you want to delete this passkey?',
      credentialId: 'cred-123',
    });

    await act(async () => {
      await result.current.confirmPasskeyAction();
    });

    expect(amplifyAuth.deleteWebAuthnCredential).toHaveBeenCalledWith({ credentialId: 'cred-123' });
    expect(result.current.pendingConfirmation).toBeNull();
  });

  it('cancels passkey confirmation without deleting', () => {
    const { result } = renderHook(() => usePasskeys());

    act(() => {
      result.current.handleDeletePasskey('cred-123');
    });
    expect(result.current.pendingConfirmation).not.toBeNull();

    act(() => {
      result.current.cancelPasskeyConfirmation();
    });
    expect(result.current.pendingConfirmation).toBeNull();
    expect(amplifyAuth.deleteWebAuthnCredential).not.toHaveBeenCalled();
  });
});
