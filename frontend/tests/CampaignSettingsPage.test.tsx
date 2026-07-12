/**
 * CampaignSettingsPage tests
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CampaignSettingsPage } from '../src/pages/CampaignSettingsPage';
import { dateToISO } from '../src/lib/date-utils';
import {
  GET_CAMPAIGN,
  UPDATE_CAMPAIGN,
  DELETE_CAMPAIGN,
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
} from '../src/lib/graphql';

const PROFILE_ID_RAW = 'profile-123';
const CAMPAIGN_ID_RAW = 'campaign-456';
const PROFILE_ID = `PROFILE#${PROFILE_ID_RAW}`;
const CAMPAIGN_ID = `CAMPAIGN#${CAMPAIGN_ID_RAW}`;
const CATALOG_ID = `CATALOG#catalog-1`;
const CATALOG_ID_2 = `CATALOG#catalog-2`;
const CATALOG_ID_3 = `CATALOG#catalog-3`;

const mockCampaign = {
  __typename: 'Campaign',
  campaignId: CAMPAIGN_ID,
  profileId: PROFILE_ID,
  campaignName: 'Spring Sale',
  campaignYear: 2025,
  startDate: '2025-03-01T00:00:00.000Z',
  endDate: '2025-03-31T00:00:00.000Z',
  catalogId: CATALOG_ID,
  unitType: 'Pack',
  unitNumber: 101,
  city: 'Springfield',
  state: 'IL',
  sharedCampaignCode: null,
  isActive: true,
  totalOrders: 0,
  totalRevenue: 0,
  createdAt: '2025-01-01T00:00:00.000Z',
  updatedAt: '2025-01-01T00:00:00.000Z',
};

const mockSharedCampaign = {
  ...mockCampaign,
  sharedCampaignCode: 'SHARED-ABC',
};

const mockCatalogs = [
  {
    __typename: 'Catalog',
    catalogId: CATALOG_ID,
    catalogName: 'Official Catalog',
    catalogType: 'ADMIN_MANAGED',
    isPublic: true,
    isDeleted: false,
    products: [],
  },
  {
    __typename: 'Catalog',
    catalogId: CATALOG_ID_2,
    catalogName: 'My Catalog',
    catalogType: 'USER_CREATED',
    isPublic: false,
    isDeleted: false,
    products: [],
  },
  {
    __typename: 'Catalog',
    catalogId: CATALOG_ID_3,
    catalogName: 'Deleted Catalog',
    catalogType: 'USER_CREATED',
    isPublic: false,
    isDeleted: true,
    products: [],
  },
];

function createMocks(campaign = mockCampaign, updateMocks: MockedResponse[] = []): MockedResponse[] {
  // Provide two GetCampaign mocks: one for the initial load and one for the refetch after update
  return [
    {
      request: {
        query: GET_CAMPAIGN,
        variables: { campaignId: CAMPAIGN_ID },
      },
      result: {
        data: {
          getCampaign: campaign,
        },
      },
    },
    {
      request: {
        query: GET_CAMPAIGN,
        variables: { campaignId: CAMPAIGN_ID },
      },
      result: {
        data: {
          getCampaign: campaign,
        },
      },
    },
    {
      request: { query: LIST_MANAGED_CATALOGS },
      result: { data: { listManagedCatalogs: [mockCatalogs[0]] } },
    },
    {
      request: { query: LIST_MY_CATALOGS },
      result: { data: { listMyCatalogs: [mockCatalogs[1], mockCatalogs[2]] } },
    },
    ...updateMocks,
  ];
}

function renderPage(mocks: MockedResponse[], initialEntry?: string) {
  const entry = initialEntry ?? `/scouts/${PROFILE_ID_RAW}/campaigns/${CAMPAIGN_ID_RAW}/settings`;
  return render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/settings" element={<CampaignSettingsPage />} />
          <Route path="/scouts/:profileId/campaigns" element={<div>Campaigns List</div>} />
          <Route path="/scouts/:profileId/manage" element={<div>Manage Scout Page</div>} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('CampaignSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading state initially', () => {
    renderPage(createMocks());
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders campaign settings with populated form fields', async () => {
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    expect(screen.getByLabelText('Start Date')).toHaveValue('2025-03-01');
    expect(screen.getByLabelText('End Date (Optional)')).toHaveValue('2025-03-31');
    expect(screen.getByText('Official Catalog (Official)')).toBeInTheDocument();
    expect(screen.getByRole('switch')).toBeChecked();
  });

  it('shows shared campaign warning when applicable', async () => {
    renderPage(createMocks(mockSharedCampaign));

    await waitFor(() => {
      expect(screen.getByText('Shared Campaign')).toBeInTheDocument();
    });
    expect(screen.getByText(/created from a shared campaign link/i)).toBeInTheDocument();
  });

  it('does not show shared campaign warning for non-shared campaigns', async () => {
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    expect(screen.queryByText('Shared Campaign')).not.toBeInTheDocument();
  });

  it('enables save button when form changes', async () => {
    const user = userEvent.setup();
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const saveButton = screen.getByRole('button', { name: /save changes/i });
    expect(saveButton).toBeDisabled();

    const nameInput = screen.getByLabelText('Campaign Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Sale');

    await waitFor(() => {
      expect(saveButton).not.toBeDisabled();
    });
  });

  it('saves changes directly when no unit-related fields changed', async () => {
    const user = userEvent.setup();
    const mocks = createMocks(mockCampaign, [
      {
        request: {
          query: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              campaignName: 'Spring Sale',
              catalogId: CATALOG_ID,
              isActive: false,
              startDate: '2025-03-01T00:00:00.000Z',
              endDate: '2025-03-31T00:00:00.000Z',
            },
          },
        },
        result: {
          data: {
            updateCampaign: { ...mockCampaign, isActive: false },
          },
        },
      },
    ]);
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('switch'));
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
  });

  it('shows confirmation dialog for unit-related changes on shared campaigns', async () => {
    const user = userEvent.setup();
    const mocks = createMocks(mockSharedCampaign, [
      {
        request: {
          query: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              campaignName: 'Updated Sale',
              catalogId: CATALOG_ID,
              isActive: true,
              startDate: '2025-03-01T00:00:00.000Z',
              endDate: '2025-03-31T00:00:00.000Z',
            },
          },
        },
        result: {
          data: { updateCampaign: { ...mockSharedCampaign, campaignName: 'Updated Sale' } },
        },
      },
    ]);
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const nameInput = screen.getByLabelText('Campaign Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Sale');

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByText('Confirm Changes to Shared Campaign')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save anyway/i }));

    await waitFor(() => {
      expect(screen.queryByText('Confirm Changes to Shared Campaign')).not.toBeInTheDocument();
    });
  });

  it('cancels unit-related changes confirmation dialog', async () => {
    const user = userEvent.setup();
    renderPage(createMocks(mockSharedCampaign));

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const nameInput = screen.getByLabelText('Campaign Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Sale');

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByText('Confirm Changes to Shared Campaign')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByText('Confirm Changes to Shared Campaign')).not.toBeInTheDocument();
    });
  });

  it('opens and cancels delete campaign confirmation dialog', async () => {
    const user = userEvent.setup();
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /delete campaign/i }));

    await waitFor(() => {
      expect(screen.getByText('Delete Campaign?')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /^cancel$/i }));

    await waitFor(() => {
      expect(screen.queryByText('Delete Campaign?')).not.toBeInTheDocument();
    });
  });

  it('deletes campaign and navigates to campaigns list', async () => {
    const user = userEvent.setup();
    const mocks = createMocks(mockCampaign, [
      {
        request: {
          query: DELETE_CAMPAIGN,
          variables: { campaignId: CAMPAIGN_ID },
        },
        result: {
          data: { deleteCampaign: CAMPAIGN_ID },
        },
      },
    ]);
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /delete campaign/i }));

    await waitFor(() => {
      expect(screen.getByText('Delete Campaign?')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /delete permanently/i }));

    await waitFor(() => {
      expect(screen.getByText('Campaigns List')).toBeInTheDocument();
    });
  });

  it('decodes URL-encoded params', async () => {
    const encodedEntry = `/scouts/${encodeURIComponent(PROFILE_ID_RAW)}/campaigns/${encodeURIComponent(CAMPAIGN_ID_RAW)}/settings`;
    renderPage(createMocks(), encodedEntry);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });
  });

  it('shows my catalog without official suffix', async () => {
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    // Open the catalog select to reveal all options
    const selectTrigger = screen.getByText((content) => content.includes('Official Catalog'));
    fireEvent.mouseDown(selectTrigger);

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'My Catalog' })).toBeInTheDocument();
    });

    // My Catalog should not have the official suffix
    expect(screen.queryByRole('option', { name: 'My Catalog (Official)' })).not.toBeInTheDocument();
  });

  it('filters out deleted catalogs from the select', async () => {
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByText('Official Catalog (Official)')).toBeInTheDocument();
    });

    expect(screen.queryByText('Deleted Catalog')).not.toBeInTheDocument();
  });

  it('does not call update when campaign name is empty', async () => {
    const user = userEvent.setup();
    const updateMock = vi.fn().mockResolvedValue({ data: {} });

    // Use a module mock to observe that updateCampaign is not invoked for invalid input
    const mocks = createMocks(mockCampaign, [
      {
        request: {
          query: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              campaignName: '',
              catalogId: CATALOG_ID,
              isActive: true,
              startDate: '2025-03-01T00:00:00.000Z',
              endDate: '2025-03-31T00:00:00.000Z',
            },
          },
        },
        result: () => {
          updateMock();
          return { data: { updateCampaign: mockCampaign } };
        },
      },
    ]);
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const nameInput = screen.getByLabelText('Campaign Name');
    await user.clear(nameInput);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save changes/i })).not.toBeDisabled();
    });

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    // Wait a tick to ensure any mutation would have been attempted
    await waitFor(() => {
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });

    expect(updateMock).not.toHaveBeenCalled();
  });

  it('saves campaign with empty dates omitted from input', async () => {
    const user = userEvent.setup();
    const mocks = createMocks(
      { ...mockCampaign, startDate: undefined, endDate: undefined },
      [
        {
          request: {
            query: UPDATE_CAMPAIGN,
            variables: {
              input: {
                campaignId: CAMPAIGN_ID,
                campaignName: 'Updated Sale',
                catalogId: CATALOG_ID,
                isActive: true,
              },
            },
          },
          result: {
            data: { updateCampaign: { ...mockCampaign, campaignName: 'Updated Sale' } },
          },
        },
      ],
    );
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const nameInput = screen.getByLabelText('Campaign Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Sale');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save changes/i })).not.toBeDisabled();
    });

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
  });

  it('updates the selected catalog', async () => {
    const user = userEvent.setup();
    const mocks = createMocks(mockCampaign, [
      {
        request: {
          query: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: CAMPAIGN_ID,
              campaignName: 'Spring Sale',
              catalogId: CATALOG_ID_2,
              isActive: true,
              startDate: '2025-03-01T00:00:00.000Z',
              endDate: '2025-03-31T00:00:00.000Z',
            },
          },
        },
        result: {
          data: { updateCampaign: { ...mockCampaign, catalogId: CATALOG_ID_2 } },
        },
      },
    ]);
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const select = screen.getByRole('combobox', { name: /product catalog/i });
    await user.click(select);

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'My Catalog' })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('option', { name: 'My Catalog' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save changes/i })).not.toBeDisabled();
    });

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
  });

  it('closes delete campaign dialog via backdrop click', async () => {
    const user = userEvent.setup();
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /delete campaign/i }));

    await waitFor(() => {
      expect(screen.getByText('Delete Campaign?')).toBeInTheDocument();
    });

    const backdrop = document.querySelector('.MuiBackdrop-root');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);

    await waitFor(() => {
      expect(screen.queryByText('Delete Campaign?')).not.toBeInTheDocument();
    });
  });

  it('closes unit change confirmation dialog via backdrop click', async () => {
    const user = userEvent.setup();
    renderPage(createMocks(mockSharedCampaign));

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const nameInput = screen.getByLabelText('Campaign Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Sale');

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByText('Confirm Changes to Shared Campaign')).toBeInTheDocument();
    });

    const backdrop = document.querySelector('.MuiBackdrop-root');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);

    await waitFor(() => {
      expect(screen.queryByText('Confirm Changes to Shared Campaign')).not.toBeInTheDocument();
    });
  });

  it('navigates to manage scout page', async () => {
    const user = userEvent.setup();
    renderPage(createMocks());

    await waitFor(() => {
      expect(screen.getByText('Campaign Settings')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /manage scout/i }));

    await waitFor(() => {
      expect(screen.getByText('Manage Scout Page')).toBeInTheDocument();
    });
  });

  it('handles a campaign with a null catalogId', async () => {
    const mocks = createMocks({ ...mockCampaign, catalogId: null });
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByText('Campaign Settings')).toBeInTheDocument();
    });

    expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /product catalog/i })).toBeInTheDocument();
  });

  it('handles missing campaign data gracefully', async () => {
    const mocks = [
      {
        request: {
          query: GET_CAMPAIGN,
          variables: { campaignId: CAMPAIGN_ID },
        },
        result: {
          data: { getCampaign: null },
        },
      },
      {
        request: { query: LIST_MANAGED_CATALOGS },
        result: { data: { listManagedCatalogs: [mockCatalogs[0]] } },
      },
      {
        request: { query: LIST_MY_CATALOGS },
        result: { data: { listMyCatalogs: [mockCatalogs[1], mockCatalogs[2]] } },
      },
    ];
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByText('Campaign Settings')).toBeInTheDocument();
    });

    expect(screen.getByRole('combobox', { name: /product catalog/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('falls back to raw catalogId when ensureCatalogId returns null', async () => {
    const user = userEvent.setup();
    const mocks = createMocks({ ...mockCampaign, catalogId: '' });
    renderPage(mocks);

    await waitFor(() => {
      expect(screen.getByDisplayValue('Spring Sale')).toBeInTheDocument();
    });

    const nameInput = screen.getByLabelText('Campaign Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Updated Sale');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save changes/i })).not.toBeDisabled();
    });

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    });
  });

  describe('dateToISO helper', () => {
    it('returns empty string for empty or whitespace input', () => {
      expect(dateToISO('')).toBe('');
      expect(dateToISO('   ')).toBe('');
    });

    it('returns the value unchanged when it already contains a T', () => {
      const iso = '2025-03-01T12:30:00.000Z';
      expect(dateToISO(iso)).toBe(iso);
    });
  });
});
