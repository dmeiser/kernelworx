/**
 * Deterministic interaction tests for CreateCampaignPage
 *
 * These tests mock useCreateCampaignPageSetup so we can exercise page-level
 * callbacks (profile changes, submit click, toast rendering) without relying
 * on MUI Select interactions in jsdom.
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { MockedProvider } from '@apollo/client/testing/react';

const mockNavigate = vi.fn();
const mockHandleSubmit = vi.fn().mockResolvedValue(undefined);
const mockSetProfileId = vi.fn();
const mockSetShareWithCreator = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({
    isAuthenticated: true,
    isLoading: false,
    account: { accountId: 'test-account-id', email: 'test@example.com' },
  })),
}));

vi.mock('../src/hooks/useCreateCampaignPageSetup', () => ({
  useCreateCampaignPageSetup: vi.fn(() => ({
    effectiveSharedCampaignCode: undefined,
    sharedCampaign: null,
    sharedCampaignLoading: false,
    sharedCampaignError: undefined,
    isSharedCampaignMode: false,
    profiles: [
      { profileId: 'profile-1', sellerName: 'Scout Alpha', isOwner: true },
      { profileId: 'profile-2', sellerName: 'Scout Beta', isOwner: false },
    ],
    profilesLoading: false,
    filteredMyCatalogs: [],
    filteredPublicCatalogs: [],
    catalogsLoading: false,
    discoveredSharedCampaigns: [],
    navigate: mockNavigate,
    handleSubmit: mockHandleSubmit,
    isFormValid: true,
    formState: {
      profileId: 'profile-1',
      setProfileId: mockSetProfileId,
      catalogId: '',
      setCatalogId: vi.fn(),
      campaignName: 'Fall Fundraiser',
      setCampaignName: vi.fn(),
      campaignYear: 2025,
      setCampaignYear: vi.fn(),
      startDate: '',
      setStartDate: vi.fn(),
      endDate: '',
      setEndDate: vi.fn(),
      unitType: '',
      setUnitType: vi.fn(),
      unitNumber: '',
      setUnitNumber: vi.fn(),
      city: '',
      setCity: vi.fn(),
      state: '',
      setState: vi.fn(),
      unitSectionExpanded: false,
      setUnitSectionExpanded: vi.fn(),
      shareWithCreator: true,
      setShareWithCreator: mockSetShareWithCreator,
      submitting: false,
      setSubmitting: vi.fn(),
      toastMessage: null,
      setToastMessage: vi.fn(),
    },
  })),
}));

import { CreateCampaignPage } from '../src/pages/CreateCampaignPage';

function createMockSetup(overrides: Record<string, unknown> = {}) {
  const base = {
    effectiveSharedCampaignCode: undefined,
    sharedCampaign: null,
    sharedCampaignLoading: false,
    sharedCampaignError: undefined,
    isSharedCampaignMode: false,
    profiles: [
      { profileId: 'profile-1', sellerName: 'Scout Alpha', isOwner: true },
      { profileId: 'profile-2', sellerName: 'Scout Beta', isOwner: false },
    ],
    profilesLoading: false,
    filteredMyCatalogs: [],
    filteredPublicCatalogs: [],
    catalogsLoading: false,
    discoveredSharedCampaigns: [],
    navigate: mockNavigate,
    handleSubmit: mockHandleSubmit,
    isFormValid: true,
    formState: {
      profileId: 'profile-1',
      setProfileId: mockSetProfileId,
      catalogId: '',
      setCatalogId: vi.fn(),
      campaignName: 'Fall Fundraiser',
      setCampaignName: vi.fn(),
      campaignYear: 2025,
      setCampaignYear: vi.fn(),
      startDate: '',
      setStartDate: vi.fn(),
      endDate: '',
      setEndDate: vi.fn(),
      unitType: '',
      setUnitType: vi.fn(),
      unitNumber: '',
      setUnitNumber: vi.fn(),
      city: '',
      setCity: vi.fn(),
      state: '',
      setState: vi.fn(),
      unitSectionExpanded: false,
      setUnitSectionExpanded: vi.fn(),
      shareWithCreator: true,
      setShareWithCreator: mockSetShareWithCreator,
      submitting: false,
      setSubmitting: vi.fn(),
      toastMessage: null,
      setToastMessage: vi.fn(),
    },
  };

  const formStateOverride = (overrides.formState as Record<string, unknown>) || {};
  delete overrides.formState;

  return {
    ...base,
    ...overrides,
    formState: {
      ...base.formState,
      ...formStateOverride,
    },
  };
}

describe('CreateCampaignPage - Interactions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls setProfileId when profile selection changes', async () => {
    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const select = await screen.findByRole('combobox', { name: /Select Profile/i });

    // Open the MUI Select dropdown and choose the second profile
    await userEvent.click(select);
    const option = await screen.findByRole('option', { name: /Scout Beta/i });
    await userEvent.click(option);

    await waitFor(() => {
      expect(mockSetProfileId).toHaveBeenCalledWith('profile-2');
    });
  });

  test('calls handleSubmit when Create Campaign button is clicked', async () => {
    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const createButton = await screen.findByRole('button', { name: /Create Campaign/i });
    expect((createButton as HTMLButtonElement).disabled).toBe(false);

    await userEvent.click(createButton);

    await waitFor(() => {
      expect(mockHandleSubmit).toHaveBeenCalledTimes(1);
    });
  });

  test('renders toast message when present', async () => {
    const toastMessage = 'Campaign saved';
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce({
      effectiveSharedCampaignCode: undefined,
      sharedCampaign: null,
      sharedCampaignLoading: false,
      sharedCampaignError: undefined,
      isSharedCampaignMode: false,
      profiles: [],
      profilesLoading: false,
      filteredMyCatalogs: [],
      filteredPublicCatalogs: [],
      catalogsLoading: false,
      discoveredSharedCampaigns: [],
      navigate: mockNavigate,
      handleSubmit: mockHandleSubmit,
      isFormValid: false,
      formState: {
        profileId: '',
        setProfileId: vi.fn(),
        catalogId: '',
        setCatalogId: vi.fn(),
        campaignName: '',
        setCampaignName: vi.fn(),
        campaignYear: new Date().getFullYear(),
        setCampaignYear: vi.fn(),
        startDate: '',
        setStartDate: vi.fn(),
        endDate: '',
        setEndDate: vi.fn(),
        unitType: '',
        setUnitType: vi.fn(),
        unitNumber: '',
        setUnitNumber: vi.fn(),
        city: '',
        setCity: vi.fn(),
        state: '',
        setState: vi.fn(),
        unitSectionExpanded: false,
        setUnitSectionExpanded: vi.fn(),
        shareWithCreator: true,
        setShareWithCreator: vi.fn(),
        submitting: false,
        setSubmitting: vi.fn(),
        toastMessage: { message: toastMessage, severity: 'success' as const },
        setToastMessage: vi.fn(),
      },
    });

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(toastMessage)).toBeInTheDocument();
    });
  });

  test('calls setUnitSectionExpanded when unit accordion is expanded', async () => {
    const mockSetUnitSectionExpanded = vi.fn();
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: { unitSectionExpanded: false, setUnitSectionExpanded: mockSetUnitSectionExpanded },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const accordionHeader = await screen.findByRole('button', { name: /Unit Information/i });
    await userEvent.click(accordionHeader);

    await waitFor(() => {
      expect(mockSetUnitSectionExpanded).toHaveBeenCalledWith(true);
    });
  });

  test('calls setUnitType when unit type selection changes', async () => {
    const mockSetUnitType = vi.fn();
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: { unitSectionExpanded: true, unitType: '', setUnitType: mockSetUnitType },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const unitTypeLabels = await screen.findAllByText(/Unit Type/i);
    const unitTypeLabel = unitTypeLabels.find((el) => el.tagName === 'LABEL') || unitTypeLabels[0];
    const unitForm = unitTypeLabel.closest('.MuiFormControl-root') as HTMLElement;
    const unitTypeSelect = unitForm.querySelector('[role="combobox"]') as HTMLElement;
    await userEvent.click(unitTypeSelect);
    const option = await screen.findByRole('option', { name: /Pack/i });
    await userEvent.click(option);

    await waitFor(() => {
      expect(mockSetUnitType).toHaveBeenCalledWith('Pack');
    });
  });

  test('calls setUnitNumber when unit number input changes', async () => {
    const mockSetUnitNumber = vi.fn();
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: {
          unitSectionExpanded: true,
          unitType: 'Pack',
          unitNumber: '',
          setUnitNumber: mockSetUnitNumber,
        },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const unitNumberInput = (await screen.findByLabelText(/Unit Number/i)) as HTMLInputElement;
    fireEvent.change(unitNumberInput, { target: { value: '42' } });

    await waitFor(() => {
      expect(mockSetUnitNumber).toHaveBeenCalledWith('42');
    });
  });

  test('calls setCity when city input changes', async () => {
    const mockSetCity = vi.fn();
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: {
          unitSectionExpanded: true,
          unitType: 'Pack',
          city: '',
          setCity: mockSetCity,
        },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const cityInput = (await screen.findByLabelText(/City/i)) as HTMLInputElement;
    fireEvent.change(cityInput, { target: { value: 'Springfield' } });

    await waitFor(() => {
      expect(mockSetCity).toHaveBeenCalledWith('Springfield');
    });
  });

  test('calls setState when state autocomplete input changes', async () => {
    const mockSetState = vi.fn();
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: {
          unitSectionExpanded: true,
          unitType: 'Pack',
          state: '',
          setState: mockSetState,
        },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const stateInput = (await screen.findByLabelText(/State/i)) as HTMLInputElement;
    fireEvent.change(stateInput, { target: { value: 'IL' } });

    await waitFor(() => {
      expect(mockSetState).toHaveBeenCalledWith('IL');
    });
  });

  test('calls setCampaignName when campaign name input changes', async () => {
    const mockSetCampaignName = vi.fn();
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: {
          campaignName: '',
          setCampaignName: mockSetCampaignName,
        },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const nameInput = (await screen.findByLabelText(/Campaign Name/i)) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'Spring Fundraiser' } });

    await waitFor(() => {
      expect(mockSetCampaignName).toHaveBeenCalledWith('Spring Fundraiser');
    });
  });

  test('calls setCampaignYear when year input changes', async () => {
    const mockSetCampaignYear = vi.fn();
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: {
          campaignYear: 2025,
          setCampaignYear: mockSetCampaignYear,
        },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const yearInput = (await screen.findByLabelText(/Year/i)) as HTMLInputElement;
    fireEvent.change(yearInput, { target: { value: '2026' } });

    await waitFor(() => {
      expect(mockSetCampaignYear).toHaveBeenCalledWith(2026);
    });
  });

  test('shows Creating... button and spinner while submitting', async () => {
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        formState: {
          submitting: true,
        },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByRole('button', { name: /Creating\.\.\./i })).toBeInTheDocument();
    expect(document.querySelector('svg[data-testid="CircularProgress"]') || document.querySelector('.MuiCircularProgress-svg')).toBeTruthy();
  });

  test('renders shared campaign section when catalog and creatorName are missing', async () => {
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        effectiveSharedCampaignCode: 'PACK123',
        isSharedCampaignMode: true,
        sharedCampaign: {
          sharedCampaignCode: 'PACK123',
          catalogId: 'catalog-1',
          catalog: undefined,
          campaignName: 'Fall',
          campaignYear: 2025,
          startDate: null,
          endDate: null,
          unitType: 'Pack',
          unitNumber: 1,
          city: 'Town',
          state: 'ST',
          createdBy: 'user#1',
          createdByName: undefined,
          creatorMessage: undefined,
          description: 'Internal description',
          createdAt: '2025-01-01T00:00:00Z',
          isActive: true,
          __typename: 'SharedCampaign',
        },
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/c/PACK123']}>
          <Routes>
            <Route path="/c/:sharedCampaignCode" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText(/Campaign by/i)).toBeInTheDocument();
    expect(screen.getByText(/Share this profile with/i)).toBeInTheDocument();
  });

  test('renders error state when sharedCampaignError is a string', async () => {
    const { useCreateCampaignPageSetup: mockSetup } = await import(
      '../src/hooks/useCreateCampaignPageSetup'
    );
    (mockSetup as any).mockReturnValueOnce(
      createMockSetup({
        effectiveSharedCampaignCode: 'BAD',
        sharedCampaignError: 'string error message',
      }),
    );

    render(
      <MockedProvider mocks={[]}>
        <MemoryRouter initialEntries={['/c/BAD']}>
          <Routes>
            <Route path="/c/:sharedCampaignCode" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    expect(await screen.findByText(/Error Loading Campaign/i)).toBeInTheDocument();
    expect(screen.getByText(/string error message/i)).toBeInTheDocument();
  });
});
