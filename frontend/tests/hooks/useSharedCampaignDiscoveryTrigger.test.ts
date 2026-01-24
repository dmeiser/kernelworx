import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useSharedCampaignDiscoveryTrigger } from '../../src/hooks/useSharedCampaignDiscoveryTrigger';

describe('useSharedCampaignDiscoveryTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does not trigger discovery in shared campaign mode', () => {
    const mockDebouncedFind = vi.fn();
    renderHook(() =>
      useSharedCampaignDiscoveryTrigger(
        true, // isSharedCampaignMode
        'Pack',
        '123',
        'Austin',
        'TX',
        'Fall Sale',
        2025,
        mockDebouncedFind,
      ),
    );

    expect(mockDebouncedFind).not.toHaveBeenCalled();
  });

  it('does not trigger discovery when unit fields are incomplete', () => {
    const mockDebouncedFind = vi.fn();
    renderHook(() =>
      useSharedCampaignDiscoveryTrigger(
        false, // isSharedCampaignMode
        'Pack',
        '', // missing unitNumber
        'Austin',
        'TX',
        'Fall Sale',
        2025,
        mockDebouncedFind,
      ),
    );

    expect(mockDebouncedFind).not.toHaveBeenCalled();
  });

  it('triggers discovery when all required fields are present', () => {
    const mockDebouncedFind = vi.fn();
    renderHook(() =>
      useSharedCampaignDiscoveryTrigger(
        false, // isSharedCampaignMode
        'Pack',
        '123',
        'Austin',
        'TX',
        'Fall Sale',
        2025,
        mockDebouncedFind,
      ),
    );

    expect(mockDebouncedFind).toHaveBeenCalledWith({
      unitType: 'Pack',
      unitNumber: '123',
      city: 'Austin',
      state: 'TX',
      campaignName: 'Fall Sale',
      campaignYear: 2025,
    });
  });

  it('re-triggers discovery when campaign fields change', () => {
    const mockDebouncedFind = vi.fn();
    const { rerender } = renderHook(
      ({ campaignName, campaignYear }) =>
        useSharedCampaignDiscoveryTrigger(
          false,
          'Pack',
          '123',
          'Austin',
          'TX',
          campaignName,
          campaignYear,
          mockDebouncedFind,
        ),
      { initialProps: { campaignName: 'Fall Sale', campaignYear: 2025 } },
    );

    expect(mockDebouncedFind).toHaveBeenCalledTimes(1);

    // Change campaign name
    rerender({ campaignName: 'Spring Sale', campaignYear: 2025 });
    expect(mockDebouncedFind).toHaveBeenCalledTimes(2);

    // Change campaign year
    rerender({ campaignName: 'Spring Sale', campaignYear: 2026 });
    expect(mockDebouncedFind).toHaveBeenCalledTimes(3);
  });
});
