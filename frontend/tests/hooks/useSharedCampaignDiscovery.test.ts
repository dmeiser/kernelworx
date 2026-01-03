import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// Mock the lazy query
const mockFindSharedCampaigns = vi.fn();

vi.mock('@apollo/client/react', () => ({
  useLazyQuery: () => [mockFindSharedCampaigns, { data: undefined }],
}));

vi.mock('../../src/lib/graphql', () => ({
  FIND_SHARED_CAMPAIGNS: { kind: 'Document', definitions: [] },
}));

// Set debounce to 0 for tests
vi.mock('../../src/lib/sharedCampaignDiscovery', () => ({
  SHARED_DISCOVERY_DEBOUNCE_MS: 0,
}));

import { useSharedCampaignDiscovery } from '../../src/hooks/useSharedCampaignDiscovery';

describe('useSharedCampaignDiscovery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('returns empty discoveredSharedCampaigns initially', () => {
    const { result } = renderHook(() => useSharedCampaignDiscovery());
    expect(result.current.discoveredSharedCampaigns).toEqual([]);
  });

  it('returns debouncedFindSharedCampaigns function', () => {
    const { result } = renderHook(() => useSharedCampaignDiscovery());
    expect(typeof result.current.debouncedFindSharedCampaigns).toBe('function');
  });

  it('does not call findSharedCampaigns when params are incomplete', () => {
    const { result } = renderHook(() => useSharedCampaignDiscovery());

    act(() => {
      result.current.debouncedFindSharedCampaigns({
        unitType: 'Pack',
        unitNumber: '',
        city: '',
        state: '',
        campaignName: '',
        campaignYear: 0,
      });
      vi.runAllTimers();
    });

    expect(mockFindSharedCampaigns).not.toHaveBeenCalled();
  });

  it('calls findSharedCampaigns when all params are provided', () => {
    const { result } = renderHook(() => useSharedCampaignDiscovery());

    act(() => {
      result.current.debouncedFindSharedCampaigns({
        unitType: 'Pack',
        unitNumber: '123',
        city: 'Austin',
        state: 'TX',
        campaignName: 'Fall Sale',
        campaignYear: 2025,
      });
      vi.runAllTimers();
    });

    expect(mockFindSharedCampaigns).toHaveBeenCalledWith({
      variables: {
        unitType: 'Pack',
        unitNumber: 123,
        city: 'Austin',
        state: 'TX',
        campaignName: 'Fall Sale',
        campaignYear: 2025,
      },
    });
  });

  it('debounces multiple calls', () => {
    const { result } = renderHook(() => useSharedCampaignDiscovery());

    act(() => {
      // First call
      result.current.debouncedFindSharedCampaigns({
        unitType: 'Pack',
        unitNumber: '123',
        city: 'Austin',
        state: 'TX',
        campaignName: 'Fall Sale',
        campaignYear: 2025,
      });

      // Second call before timeout
      result.current.debouncedFindSharedCampaigns({
        unitType: 'Troop',
        unitNumber: '456',
        city: 'Dallas',
        state: 'TX',
        campaignName: 'Spring Sale',
        campaignYear: 2026,
      });

      vi.runAllTimers();
    });

    // Only the last call should have been made
    expect(mockFindSharedCampaigns).toHaveBeenCalledTimes(1);
    expect(mockFindSharedCampaigns).toHaveBeenCalledWith({
      variables: {
        unitType: 'Troop',
        unitNumber: 456,
        city: 'Dallas',
        state: 'TX',
        campaignName: 'Spring Sale',
        campaignYear: 2026,
      },
    });
  });
});
