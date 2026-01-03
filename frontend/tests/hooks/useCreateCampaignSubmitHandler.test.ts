import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// Mock validation hook
const mockValidateProfileSelection = vi.fn();
const mockValidateUnitFields = vi.fn();

vi.mock('../../src/hooks/useCreateCampaignValidation', () => ({
  useCreateCampaignValidation: () => ({
    isFormValid: true,
    validateProfileSelection: mockValidateProfileSelection,
    validateUnitFields: mockValidateUnitFields,
  }),
}));

// Mock submit hook
const mockSubmitCampaign = vi.fn();

vi.mock('../../src/hooks/useCreateCampaignSubmit', () => ({
  useCreateCampaignSubmit: () => ({
    handleSubmit: mockSubmitCampaign,
  }),
}));

import { useCreateCampaignSubmitHandler } from '../../src/hooks/useCreateCampaignSubmitHandler';

describe('useCreateCampaignSubmitHandler', () => {
  const createMockFormState = (overrides = {}) => ({
    profileId: 'profile-1',
    campaignName: 'Fall Sale',
    campaignYear: 2025,
    catalogId: 'catalog-1',
    startDate: '',
    endDate: '',
    unitType: '',
    unitNumber: '',
    city: '',
    state: '',
    shareWithCreator: false,
    submitting: false,
    toastMessage: null,
    setProfileId: vi.fn(),
    setCampaignName: vi.fn(),
    setCampaignYear: vi.fn(),
    setCatalogId: vi.fn(),
    setStartDate: vi.fn(),
    setEndDate: vi.fn(),
    setUnitType: vi.fn(),
    setUnitNumber: vi.fn(),
    setCity: vi.fn(),
    setState: vi.fn(),
    setShareWithCreator: vi.fn(),
    setSubmitting: vi.fn(),
    setToastMessage: vi.fn(),
    ...overrides,
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockValidateProfileSelection.mockReturnValue({ isValid: true, error: null });
    mockValidateUnitFields.mockReturnValue({ isValid: true, error: null });
    mockSubmitCampaign.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns handleSubmit and isFormValid', () => {
    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    expect(result.current.handleSubmit).toBeDefined();
    expect(result.current.isFormValid).toBe(true);
  });

  it('shows error when profile validation fails', async () => {
    mockValidateProfileSelection.mockReturnValue({ isValid: false, error: 'Please select a profile' });

    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    await act(async () => {
      await result.current.handleSubmit({
        isSharedCampaignMode: false,
        effectiveSharedCampaignCode: undefined,
        sharedCampaignCreatedByName: undefined,
      });
    });

    expect(formState.setToastMessage).toHaveBeenCalledWith({
      message: 'Please select a profile',
      severity: 'error',
    });
    expect(mockSubmitCampaign).not.toHaveBeenCalled();
  });

  it('shows error when unit validation fails', async () => {
    mockValidateUnitFields.mockReturnValue({
      isValid: false,
      error: 'When specifying a unit, all fields are required',
    });

    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    await act(async () => {
      await result.current.handleSubmit({
        isSharedCampaignMode: false,
        effectiveSharedCampaignCode: undefined,
        sharedCampaignCreatedByName: undefined,
      });
    });

    expect(formState.setToastMessage).toHaveBeenCalledWith({
      message: 'When specifying a unit, all fields are required',
      severity: 'error',
    });
    expect(mockSubmitCampaign).not.toHaveBeenCalled();
  });

  it('submits campaign when validation passes', async () => {
    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    await act(async () => {
      await result.current.handleSubmit({
        isSharedCampaignMode: false,
        effectiveSharedCampaignCode: undefined,
        sharedCampaignCreatedByName: undefined,
      });
    });

    expect(formState.setSubmitting).toHaveBeenCalledWith(true);
    expect(mockSubmitCampaign).toHaveBeenCalled();
    expect(formState.setSubmitting).toHaveBeenCalledWith(false);
  });

  it('passes correct params to submitCampaign', async () => {
    const formState = createMockFormState({
      profileId: 'profile-abc',
      campaignName: 'Spring Sale',
      campaignYear: 2026,
      catalogId: 'catalog-xyz',
      unitType: 'Pack',
      unitNumber: '42',
      city: 'Dallas',
      state: 'TX',
      startDate: '2026-01-01',
      endDate: '2026-03-31',
      shareWithCreator: true,
    });
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    await act(async () => {
      await result.current.handleSubmit({
        isSharedCampaignMode: true,
        effectiveSharedCampaignCode: 'PACK456',
        sharedCampaignCreatedByName: 'Jane Leader',
      });
    });

    const submitCall = mockSubmitCampaign.mock.calls[0][0];
    expect(submitCall.profileId).toBe('profile-abc');
    expect(submitCall.campaignName).toBe('Spring Sale');
    expect(submitCall.campaignYear).toBe(2026);
    expect(submitCall.catalogId).toBe('catalog-xyz');
    expect(submitCall.unitType).toBe('Pack');
    expect(submitCall.unitNumber).toBe('42');
    expect(submitCall.city).toBe('Dallas');
    expect(submitCall.state).toBe('TX');
    expect(submitCall.isSharedCampaignMode).toBe(true);
    expect(submitCall.effectiveSharedCampaignCode).toBe('PACK456');
    expect(submitCall.shareWithCreator).toBe(true);
    expect(submitCall.sharedCampaignCreatedByName).toBe('Jane Leader');
  });

  it('sets submitting to false even when submit throws', async () => {
    mockSubmitCampaign.mockRejectedValue(new Error('Network error'));

    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    await act(async () => {
      try {
        await result.current.handleSubmit({
          isSharedCampaignMode: false,
          effectiveSharedCampaignCode: undefined,
          sharedCampaignCreatedByName: undefined,
        });
      } catch {
        // Expected to throw
      }
    });

    expect(formState.setSubmitting).toHaveBeenCalledWith(false);
  });

  it('calls onSuccess callback with message', async () => {
    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    // Capture the onSuccess callback
    await act(async () => {
      await result.current.handleSubmit({
        isSharedCampaignMode: false,
        effectiveSharedCampaignCode: undefined,
        sharedCampaignCreatedByName: undefined,
      });
    });

    // Get the onSuccess callback that was passed
    const submitCall = mockSubmitCampaign.mock.calls[0][0];
    submitCall.onSuccess('Campaign created!');

    expect(formState.setToastMessage).toHaveBeenCalledWith({
      message: 'Campaign created!',
      severity: 'success',
    });
  });

  it('calls onError callback with message', async () => {
    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    await act(async () => {
      await result.current.handleSubmit({
        isSharedCampaignMode: false,
        effectiveSharedCampaignCode: undefined,
        sharedCampaignCreatedByName: undefined,
      });
    });

    // Get the onError callback that was passed
    const submitCall = mockSubmitCampaign.mock.calls[0][0];
    submitCall.onError('Failed to create campaign');

    expect(formState.setToastMessage).toHaveBeenCalledWith({
      message: 'Failed to create campaign',
      severity: 'error',
    });
  });

  it('handles validation failure with null error message gracefully', async () => {
    mockValidateProfileSelection.mockReturnValue({ isValid: false, error: null });

    const formState = createMockFormState();
    const { result } = renderHook(() => useCreateCampaignSubmitHandler(formState));

    await act(async () => {
      await result.current.handleSubmit({
        isSharedCampaignMode: false,
        effectiveSharedCampaignCode: undefined,
        sharedCampaignCreatedByName: undefined,
      });
    });

    expect(formState.setToastMessage).toHaveBeenCalledWith({
      message: 'Validation failed',
      severity: 'error',
    });
  });
});
