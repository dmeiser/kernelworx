import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';

// Mock react-router-dom
const mockLocation = { state: null as any };
vi.mock('react-router-dom', () => ({
  useLocation: () => mockLocation,
}));

import { useProfileRefetch } from '../../src/hooks/useProfileRefetch';

describe('useProfileRefetch', () => {
  beforeEach(() => {
    mockLocation.state = null;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('does not refetch when location state is null', () => {
    const mockRefetch = vi.fn();
    renderHook(() => useProfileRefetch(mockRefetch));

    expect(mockRefetch).not.toHaveBeenCalled();
  });

  it('does not refetch when fromProfileCreation is false', () => {
    mockLocation.state = { fromProfileCreation: false };
    const mockRefetch = vi.fn();
    renderHook(() => useProfileRefetch(mockRefetch));

    expect(mockRefetch).not.toHaveBeenCalled();
  });

  it('refetches when fromProfileCreation is true', () => {
    mockLocation.state = { fromProfileCreation: true };
    const mockRefetch = vi.fn();
    renderHook(() => useProfileRefetch(mockRefetch));

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });
});
