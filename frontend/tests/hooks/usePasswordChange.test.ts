import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import * as amplifyAuth from 'aws-amplify/auth';
import { usePasswordChange } from '../../src/hooks/usePasswordChange';

/* cspell:disable */

vi.mock('aws-amplify/auth', () => ({
  updatePassword: vi.fn(),
}));

describe('usePasswordChange', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('rejects a password missing required character classes', async () => {
    const { result } = renderHook(() => usePasswordChange());

    act(() => {
      result.current.setCurrentPassword('oldpassword123!');
      result.current.setNewPassword('aaaaaaaaaaaaaaaa');
      result.current.setConfirmPassword('aaaaaaaaaaaaaaaa');
    });

    await act(async () => {
      await result.current.handlePasswordChange({ preventDefault: () => {} } as any);
    });

    expect(result.current.passwordError).toBe(
      'Password must be at least 15 characters and include uppercase, lowercase, number, and symbol',
    );
    expect(amplifyAuth.updatePassword).not.toHaveBeenCalled();
  });

  it('rejects a password that is too short', async () => {
    const { result } = renderHook(() => usePasswordChange());

    act(() => {
      result.current.setCurrentPassword('oldpassword123!');
      result.current.setNewPassword('Aa1!short');
      result.current.setConfirmPassword('Aa1!short');
    });

    await act(async () => {
      await result.current.handlePasswordChange({ preventDefault: () => {} } as any);
    });

    expect(result.current.passwordError).toBe(
      'Password must be at least 15 characters and include uppercase, lowercase, number, and symbol',
    );
    expect(amplifyAuth.updatePassword).not.toHaveBeenCalled();
  });

  it('rejects mismatched passwords', async () => {
    const { result } = renderHook(() => usePasswordChange());

    act(() => {
      result.current.setCurrentPassword('oldpassword123!');
      result.current.setNewPassword('ValidPass1234!@#');
      result.current.setConfirmPassword('DifferentPass1234!@#');
    });

    await act(async () => {
      await result.current.handlePasswordChange({ preventDefault: () => {} } as any);
    });

    expect(result.current.passwordError).toBe('New passwords do not match');
    expect(amplifyAuth.updatePassword).not.toHaveBeenCalled();
  });

  it('accepts a valid password and calls updatePassword', async () => {
    vi.mocked(amplifyAuth.updatePassword).mockResolvedValue(undefined as any);
    const { result } = renderHook(() => usePasswordChange());

    act(() => {
      result.current.setCurrentPassword('oldpassword123!');
      result.current.setNewPassword('ValidPass1234!@#');
      result.current.setConfirmPassword('ValidPass1234!@#');
    });

    await act(async () => {
      await result.current.handlePasswordChange({ preventDefault: () => {} } as any);
    });

    expect(result.current.passwordError).toBeNull();
    expect(result.current.passwordSuccess).toBe(true);
    expect(amplifyAuth.updatePassword).toHaveBeenCalledWith({
      oldPassword: 'oldpassword123!',
      newPassword: 'ValidPass1234!@#',
    });
  });


  it('surfaces an error message when updatePassword rejects with an Error', async () => {
    vi.mocked(amplifyAuth.updatePassword).mockRejectedValue(new Error('update failed'));
    const { result } = renderHook(() => usePasswordChange());

    act(() => {
      result.current.setCurrentPassword('oldpassword123!');
      result.current.setNewPassword('ValidPass1234!@#');
      result.current.setConfirmPassword('ValidPass1234!@#');
    });

    await act(async () => {
      await result.current.handlePasswordChange({ preventDefault: () => {} } as any);
    });

    expect(result.current.passwordError).toBe('update failed');
    expect(result.current.passwordSuccess).toBe(false);
    expect(result.current.passwordLoading).toBe(false);
  });

  it('surfaces the message property when updatePassword rejects with an object', async () => {
    vi.mocked(amplifyAuth.updatePassword).mockRejectedValue({ message: 'wrapped message' });
    const { result } = renderHook(() => usePasswordChange());

    act(() => {
      result.current.setCurrentPassword('oldpassword123!');
      result.current.setNewPassword('ValidPass1234!@#');
      result.current.setConfirmPassword('ValidPass1234!@#');
    });

    await act(async () => {
      await result.current.handlePasswordChange({ preventDefault: () => {} } as any);
    });

    expect(result.current.passwordError).toBe('wrapped message');
    expect(result.current.passwordLoading).toBe(false);
  });

  it('falls back to a generic message when updatePassword rejects with a non-error value', async () => {
    vi.mocked(amplifyAuth.updatePassword).mockRejectedValue('nope');
    const { result } = renderHook(() => usePasswordChange());

    act(() => {
      result.current.setCurrentPassword('oldpassword123!');
      result.current.setNewPassword('ValidPass1234!@#');
      result.current.setConfirmPassword('ValidPass1234!@#');
    });

    await act(async () => {
      await result.current.handlePasswordChange({ preventDefault: () => {} } as any);
    });

    expect(result.current.passwordError).toBe('Failed to change password. Please check your current password.');
    expect(result.current.passwordLoading).toBe(false);
  });

});
