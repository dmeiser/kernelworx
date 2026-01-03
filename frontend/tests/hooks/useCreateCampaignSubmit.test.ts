import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Mock dependencies before importing the hook
const mockNavigate = vi.fn();
const mockCreateCampaign = vi.fn();

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock('@apollo/client/react', () => ({
  useMutation: () => [mockCreateCampaign, { loading: false }],
}));

vi.mock('../../src/lib/graphql', () => ({
  CREATE_CAMPAIGN: { kind: 'Document', definitions: [] },
  LIST_MY_PROFILES: { kind: 'Document', definitions: [] },
  LIST_CAMPAIGNS_BY_PROFILE: { kind: 'Document', definitions: [] },
}));

vi.mock('../../src/lib/ids', () => ({
  ensureProfileId: (id: string) => (id.startsWith('PROFILE#') ? id : `PROFILE#${id}`),
  ensureCatalogId: (id: string) => (id.startsWith('CATALOG#') ? id : `CATALOG#${id}`),
  toUrlId: (id: string) => id.replace(/^(PROFILE#|CATALOG#|CAMPAIGN#)/, ''),
}));

import { useCreateCampaignSubmit } from '../../src/hooks/useCreateCampaignSubmit';

describe('useCreateCampaignSubmit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const createBaseParams = (overrides = {}) => ({
    profileId: 'profile-1',
    campaignName: 'Fall Sale',
    campaignYear: 2025,
    catalogId: 'catalog-1',
    unitType: '',
    unitNumber: '',
    city: '',
    state: '',
    startDate: '',
    endDate: '',
    isSharedCampaignMode: false,
    effectiveSharedCampaignCode: undefined,
    shareWithCreator: false,
    sharedCampaignCreatedByName: undefined,
    onSuccess: vi.fn(),
    onError: vi.fn(),
    ...overrides,
  });

  it('returns handleSubmit function', () => {
    const { result } = renderHook(() => useCreateCampaignSubmit());
    expect(result.current.handleSubmit).toBeDefined();
    expect(typeof result.current.handleSubmit).toBe('function');
  });

  it('calls createCampaign mutation on submit in manual mode', async () => {
    mockCreateCampaign.mockResolvedValue({
      data: {
        createCampaign: {
          campaignId: 'CAMPAIGN#camp-123',
          campaignName: 'Fall Sale',
          campaignYear: 2025,
        },
      },
    });

    const { result } = renderHook(() => useCreateCampaignSubmit());
    const params = createBaseParams();

    await act(async () => {
      await result.current.handleSubmit(params);
    });

    expect(mockCreateCampaign).toHaveBeenCalled();
    expect(params.onSuccess).toHaveBeenCalledWith('Campaign created successfully!');
    expect(mockNavigate).toHaveBeenCalledWith('/scouts/profile-1/campaigns/camp-123');
  });

  it('calls createCampaign mutation with unit fields when provided', async () => {
    mockCreateCampaign.mockResolvedValue({
      data: {
        createCampaign: {
          campaignId: 'CAMPAIGN#camp-123',
          campaignName: 'Fall Sale',
          campaignYear: 2025,
        },
      },
    });

    const { result } = renderHook(() => useCreateCampaignSubmit());
    const params = createBaseParams({
      unitType: 'Pack',
      unitNumber: '123',
      city: 'Austin',
      state: 'TX',
    });

    await act(async () => {
      await result.current.handleSubmit(params);
    });

    expect(mockCreateCampaign).toHaveBeenCalled();
    const callArgs = mockCreateCampaign.mock.calls[0][0];
    expect(callArgs.variables.input.unitType).toBe('Pack');
    expect(callArgs.variables.input.unitNumber).toBe(123);
    expect(callArgs.variables.input.city).toBe('Austin');
    expect(callArgs.variables.input.state).toBe('TX');
  });

  it('handles shared campaign mode with shareWithCreator', async () => {
    mockCreateCampaign.mockResolvedValue({
      data: {
        createCampaign: {
          campaignId: 'CAMPAIGN#camp-123',
          campaignName: 'Fall Sale',
          campaignYear: 2025,
        },
      },
    });

    const { result } = renderHook(() => useCreateCampaignSubmit());
    const params = createBaseParams({
      isSharedCampaignMode: true,
      effectiveSharedCampaignCode: 'PACK123',
      shareWithCreator: true,
      sharedCampaignCreatedByName: 'John Leader',
    });

    await act(async () => {
      await result.current.handleSubmit(params);
    });

    expect(mockCreateCampaign).toHaveBeenCalled();
    const callArgs = mockCreateCampaign.mock.calls[0][0];
    expect(callArgs.variables.input.sharedCampaignCode).toBe('PACK123');
    expect(callArgs.variables.input.shareWithCreator).toBe(true);
    expect(params.onSuccess).toHaveBeenCalledWith('Campaign created and shared with John Leader!');
  });

  it('handles shared campaign mode without sharing', async () => {
    mockCreateCampaign.mockResolvedValue({
      data: {
        createCampaign: {
          campaignId: 'CAMPAIGN#camp-123',
          campaignName: 'Fall Sale',
          campaignYear: 2025,
        },
      },
    });

    const { result } = renderHook(() => useCreateCampaignSubmit());
    const params = createBaseParams({
      isSharedCampaignMode: true,
      effectiveSharedCampaignCode: 'PACK123',
      shareWithCreator: false,
    });

    await act(async () => {
      await result.current.handleSubmit(params);
    });

    expect(params.onSuccess).toHaveBeenCalledWith('Campaign created successfully!');
  });

  it('handles dates when provided', async () => {
    mockCreateCampaign.mockResolvedValue({
      data: {
        createCampaign: {
          campaignId: 'CAMPAIGN#camp-123',
          campaignName: 'Fall Sale',
          campaignYear: 2025,
        },
      },
    });

    const { result } = renderHook(() => useCreateCampaignSubmit());
    const params = createBaseParams({
      startDate: '2025-09-01',
      endDate: '2025-12-31',
    });

    await act(async () => {
      await result.current.handleSubmit(params);
    });

    const callArgs = mockCreateCampaign.mock.calls[0][0];
    expect(callArgs.variables.input.startDate).toBeDefined();
    expect(callArgs.variables.input.endDate).toBeDefined();
  });

  it('calls onError when mutation fails', async () => {
    mockCreateCampaign.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useCreateCampaignSubmit());
    const params = createBaseParams();

    await act(async () => {
      await result.current.handleSubmit(params);
    });

    expect(params.onError).toHaveBeenCalledWith('Failed to create campaign. Please try again.');
    expect(params.onSuccess).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('does not navigate when createCampaign returns no data', async () => {
    mockCreateCampaign.mockResolvedValue({ data: null });

    const { result } = renderHook(() => useCreateCampaignSubmit());
    const params = createBaseParams();

    await act(async () => {
      await result.current.handleSubmit(params);
    });

    expect(mockNavigate).not.toHaveBeenCalled();
    expect(params.onSuccess).not.toHaveBeenCalled();
  });
});
