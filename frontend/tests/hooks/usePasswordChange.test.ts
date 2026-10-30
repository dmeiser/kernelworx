import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import * as amplifyAuth from 'aws-amplify/auth';
import { usePasswordChange } from '../../src/hooks/usePasswordChange';

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
});
