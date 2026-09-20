/**
 * Tests for usePasskeys hook
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import * as amplifyAuth from 'aws-amplify/auth';
import { usePasskeys } from '../../src/hooks/usePasskeys';

vi.mock('aws-amplify/auth', () => ({
  associateWebAuthnCredential: vi.fn(),
  listWebAuthnCredentials: vi.fn(),
  deleteWebAuthnCredential: vi.fn(),
  updateMFAPreference: vi.fn(),
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

  it('registers passkey directly without disabling TOTP MFA (coexistence)', async () => {
    const { result } = renderHook(() => usePasskeys());

    act(() => {
      result.current.setPasskeyName('New Security Key');
    });

    await act(async () => {
      await result.current.handleRegisterPasskey();
    });

    expect(amplifyAuth.associateWebAuthnCredential).toHaveBeenCalledTimes(1);
    // Crucial two-path MFA assertion: updateMFAPreference is NEVER called to disable TOTP
    expect(amplifyAuth.updateMFAPreference).not.toHaveBeenCalled();
    // No confirmation dialog needed
    expect(result.current.pendingConfirmation).toBeNull();
    expect(result.current.passkeySuccess).toBe(true);
    expect(result.current.passkeyName).toBe('');
    expect(amplifyAuth.listWebAuthnCredentials).toHaveBeenCalled();
  });

  it('sets error message when associateWebAuthnCredential fails', async () => {
    vi.mocked(amplifyAuth.associateWebAuthnCredential).mockRejectedValue(new Error('Passkey rejected'));
    const { result } = renderHook(() => usePasskeys());

    act(() => {
      result.current.setPasskeyName('Phone');
    });

    await act(async () => {
      await result.current.handleRegisterPasskey();
    });

    expect(result.current.passkeyError).toBe('Passkey rejected');
    expect(result.current.passkeySuccess).toBe(false);
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
