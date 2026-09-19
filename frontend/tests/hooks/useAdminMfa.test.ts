import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAdminMfa } from '../../src/hooks/useAdminMfa';

describe('useAdminMfa', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('initializes with isMfaRequired false', () => {
    const { result } = renderHook(() => useAdminMfa());
    expect(result.current.isMfaRequired).toBe(false);
  });

  it('updates isMfaRequired when triggerMfaRequired is called', () => {
    const { result } = renderHook(() => useAdminMfa());

    act(() => {
      result.current.triggerMfaRequired();
    });

    expect(result.current.isMfaRequired).toBe(true);
  });

  it('resets isMfaRequired when resetMfaRequired is called', () => {
    const { result } = renderHook(() => useAdminMfa());

    act(() => {
      result.current.triggerMfaRequired();
    });
    expect(result.current.isMfaRequired).toBe(true);

    act(() => {
      result.current.resetMfaRequired();
    });
    expect(result.current.isMfaRequired).toBe(false);
  });

  it('listens for mfa-required window event', () => {
    const { result } = renderHook(() => useAdminMfa());

    expect(result.current.isMfaRequired).toBe(false);

    act(() => {
      window.dispatchEvent(
        new CustomEvent('mfa-required', {
          detail: { message: 'MFA required' },
        }),
      );
    });

    expect(result.current.isMfaRequired).toBe(true);
  });

  it('cleans up event listener on unmount', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const { unmount } = renderHook(() => useAdminMfa());

    unmount();

    expect(removeSpy).toHaveBeenCalledWith('mfa-required', expect.any(Function));
    removeSpy.mockRestore();
  });
});
