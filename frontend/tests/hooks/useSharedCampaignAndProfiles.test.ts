import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const mockUseQuery = vi.fn();
vi.mock('@apollo/client/react', () => ({
  useApolloClient: () => ({ query: vi.fn() }),
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}));

const mockFetchAllMyProfiles = vi.fn();
vi.mock('../../src/lib/myProfiles', () => ({
  fetchAllMyProfiles: () => mockFetchAllMyProfiles(),
}));

import { useSharedCampaignAndProfiles } from '../../src/hooks/useSharedCampaignAndProfiles';
import { GET_SHARED_CAMPAIGN } from '../../src/lib/graphql';

describe('useSharedCampaignAndProfiles', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchAllMyProfiles.mockResolvedValue([]);
  });

  it('skips query when effectiveSharedCampaignCode is undefined', () => {
    mockUseQuery.mockReturnValue({
      data: undefined,
      loading: false,
      error: undefined,
    });

    const { result } = renderHook(() => useSharedCampaignAndProfiles(undefined));

    expect(mockUseQuery).toHaveBeenCalledWith(GET_SHARED_CAMPAIGN, {
      variables: { sharedCampaignCode: undefined },
      skip: true,
    });
    expect(result.current.sharedCampaign).toBeNull();
    expect(result.current.isSharedCampaignMode).toBe(false);
  });

  it('queries shared campaign when code is provided and determines isSharedCampaignMode', () => {
    const mockCampaign = {
      sharedCampaignCode: 'CODE123',
      isActive: true,
      catalog: { catalogId: 'cat-1', catalogName: 'Test' },
    };
    mockUseQuery.mockReturnValue({
      data: { getSharedCampaign: mockCampaign },
      loading: false,
      error: undefined,
    });

    const { result } = renderHook(() => useSharedCampaignAndProfiles('CODE123'));

    expect(mockUseQuery).toHaveBeenCalledWith(GET_SHARED_CAMPAIGN, {
      variables: { sharedCampaignCode: 'CODE123' },
      skip: false,
    });
    expect(result.current.sharedCampaign).toEqual(mockCampaign);
    expect(result.current.isSharedCampaignMode).toBe(true);
  });

  it('sets isSharedCampaignMode to false if campaign is inactive', () => {
    const mockCampaign = {
      sharedCampaignCode: 'CODE123',
      isActive: false,
      catalog: { catalogId: 'cat-1', catalogName: 'Test' },
    };
    mockUseQuery.mockReturnValue({
      data: { getSharedCampaign: mockCampaign },
      loading: false,
      error: undefined,
    });

    const { result } = renderHook(() => useSharedCampaignAndProfiles('CODE123'));

    expect(result.current.isSharedCampaignMode).toBe(false);
  });
});
