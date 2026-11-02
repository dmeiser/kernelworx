import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useLocation: () => ({ state: null }),
}));

const mockUseQuery = vi.fn();
vi.mock('@apollo/client/react', () => ({
  useQuery: (...args: unknown[]) => mockUseQuery(...args),
}));

const mockSharedCampaign = {
  sharedCampaignCode: 'CODE123',
  campaignName: 'Fall Fundraiser',
  campaignYear: 2025,
  catalogId: 'cat-1',
  catalog: { catalogId: 'cat-1', catalogName: 'Catalog 1' },
  isActive: true,
  unitType: 'Pack',
  unitNumber: 100,
  city: 'Austin',
  state: 'TX',
  createdBy: 'user-1',
  createdByName: 'Leader Bob',
  createdAt: '2025-01-01T00:00:00Z',
};

const mockProfiles = [{ profileId: 'prof-1', sellerName: 'Scout 1', isOwner: true }];

const mockUseSharedCampaignAndProfiles = vi.fn();
vi.mock('../../src/hooks/useSharedCampaignAndProfiles', () => ({
  useSharedCampaignAndProfiles: (code: string | undefined) => mockUseSharedCampaignAndProfiles(code),
}));

const mockCatalogsData = {
  filteredPublicCatalogs: [],
  filteredMyCatalogs: [],
  catalogsLoading: false,
};
const mockUseCatalogsData = vi.fn((_isShared: boolean) => mockCatalogsData);
vi.mock('../../src/hooks/useCatalogsData', () => ({
  useCatalogsData: (isShared: boolean) => mockUseCatalogsData(isShared),
}));

const mockUseProfileEffects = vi.fn();
vi.mock('../../src/hooks/useProfileEffects', () => ({
  useProfileEffects: (...args: [unknown, unknown, unknown, unknown, unknown, unknown, unknown]) =>
    mockUseProfileEffects(...args),
}));

const mockUseProfileRefetch = vi.fn();
vi.mock('../../src/hooks/useProfileRefetch', () => ({
  useProfileRefetch: (fn: () => void) => mockUseProfileRefetch(fn),
}));

const mockUseSharedCampaignFormInit = vi.fn();
vi.mock('../../src/hooks/useSharedCampaignFormInit', () => ({
  useSharedCampaignFormInit: (
    ...args: [
      unknown,
      unknown,
      unknown,
      unknown,
      unknown,
      unknown,
      unknown,
      unknown,
      unknown,
      unknown,
    ]
  ) => mockUseSharedCampaignFormInit(...args),
}));

const mockUseCreateCampaignSubmitHandler = vi.fn((_formState: unknown, _isShared: boolean) => ({
  handleSubmit: vi.fn(),
  isFormValid: true,
}));
vi.mock('../../src/hooks/useCreateCampaignSubmitHandler', () => ({
  useCreateCampaignSubmitHandler: (formState: unknown, isShared: boolean) =>
    mockUseCreateCampaignSubmitHandler(formState, isShared),
}));

import { useCreateCampaignPageSetup } from '../../src/hooks/useCreateCampaignPageSetup';

describe('useCreateCampaignPageSetup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSharedCampaignAndProfiles.mockReturnValue({
      sharedCampaign: mockSharedCampaign,
      sharedCampaignLoading: false,
      sharedCampaignError: undefined,
      profiles: mockProfiles,
      profilesLoading: false,
      refetchProfiles: vi.fn(),
      isSharedCampaignMode: true,
    });
  });

  it('delegates shared campaign querying to useSharedCampaignAndProfiles without duplicate useQuery calls', () => {
    const { result } = renderHook(() => useCreateCampaignPageSetup('CODE123'));

    expect(mockUseSharedCampaignAndProfiles).toHaveBeenCalledWith('CODE123');
    // useCreateCampaignPageSetup itself must not call useQuery directly
    expect(mockUseQuery).not.toHaveBeenCalled();

    // Reuses sharedCampaign, loading, error from useSharedCampaignAndProfiles
    expect(result.current.sharedCampaign).toBe(mockSharedCampaign);
    expect(result.current.sharedCampaignLoading).toBe(false);
    expect(result.current.sharedCampaignError).toBeUndefined();
    expect(result.current.isSharedCampaignMode).toBe(true);
    expect(result.current.profiles).toBe(mockProfiles);
  });

  it('does not expose discoveredSharedCampaigns or trigger discovery requests', () => {
    const { result } = renderHook(() => useCreateCampaignPageSetup('CODE123'));

    // discoveredSharedCampaigns was removed from return value as it is unused by CreateCampaignPage
    expect('discoveredSharedCampaigns' in result.current).toBe(false);
  });

  it('preserves formState reference stability across rerenders when form values do not change', () => {
    const { result, rerender } = renderHook(() => useCreateCampaignPageSetup('CODE123'));
    const initialFormState = result.current.formState;

    rerender();

    expect(result.current.formState).toBe(initialFormState);
  });

  it('passes shared campaign from useSharedCampaignAndProfiles to useSharedCampaignFormInit', () => {
    renderHook(() => useCreateCampaignPageSetup('CODE123'));

    expect(mockUseSharedCampaignFormInit).toHaveBeenCalledWith(
      mockSharedCampaign,
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
  });
});
