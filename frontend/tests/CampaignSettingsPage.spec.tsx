import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { CampaignSettingsPage } from '../src/pages/CampaignSettingsPage';
import {
  GET_CAMPAIGN,
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  DELETE_CAMPAIGN,
  UPDATE_CAMPAIGN,
} from '../src/lib/graphql';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockCampaign = {
  campaignId: 'campaign-123',
  campaignName: 'Fall',
  campaignYear: 2025,
  startDate: '2025-09-01T00:00:00.000Z',
  endDate: '2025-12-01T23:59:59.999Z',
  catalogId: 'catalog-1',
  profileId: 'profile-123',
  sharedCampaignCode: 'PACK123F25',
};

const mockCatalogs = [
  { catalogId: 'catalog-1', catalogName: 'Official', catalogType: 'ADMIN_MANAGED', isDeleted: false },
];

const createMocks = () => {
  const dbCampaignId = `CAMPAIGN#${mockCampaign.campaignId}`;
  const dbProfileId = `PROFILE#${mockCampaign.profileId}`;
  return [
    {
      request: { query: GET_CAMPAIGN, variables: { campaignId: dbCampaignId } },
      result: {
        data: {
          getCampaign: {
            ...mockCampaign,
            campaignId: dbCampaignId,
            profileId: dbProfileId,
            catalogId: mockCampaign.catalogId,
            catalog: {
              catalogId: mockCatalogs[0].catalogId,
              catalogName: mockCatalogs[0].catalogName,
              catalogType: mockCatalogs[0].catalogType,
              isDeleted: mockCatalogs[0].isDeleted,
            },
          },
        },
      },
    },
    { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: mockCatalogs } } },
    { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [] } } },
  ];
};

const renderWithMocks = (mocks: any[]) =>
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter
        initialEntries={[`/scouts/${mockCampaign.profileId}/campaigns/${mockCampaign.campaignId}/settings`]}
      >
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/settings" element={<CampaignSettingsPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );

describe('CampaignSettingsPage (core flows)', () => {
  it('shows Shared Campaign banner for shared campaigns', async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByText('Shared Campaign')).toBeTruthy());
  });

  it('shows confirmation dialog when changing campaign name on shared campaign', async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByLabelText('Campaign Name')).toBeTruthy());

    const nameInput = screen.getByLabelText('Campaign Name');
    fireEvent.change(nameInput, { target: { value: 'Winter' } });

    const save = screen.getByRole('button', { name: /save changes/i });
    fireEvent.click(save);

    await waitFor(() => expect(screen.getByText('Confirm Changes to Shared Campaign')).toBeTruthy());
  });

  it('allows changing start date', async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByLabelText('Start Date')).toBeTruthy());

    const startDateInput = screen.getByLabelText('Start Date');
    fireEvent.change(startDateInput, { target: { value: '2025-10-01' } });

    // Save button should be enabled after change
    const save = screen.getByRole('button', { name: /save changes/i });
    expect(save).not.toBeDisabled();
  });

  it('allows changing end date', async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByLabelText(/End Date/i)).toBeTruthy());

    const endDateInput = screen.getByLabelText(/End Date/i);
    fireEvent.change(endDateInput, { target: { value: '2025-12-31' } });

    const save = screen.getByRole('button', { name: /save changes/i });
    expect(save).not.toBeDisabled();
  });

  it('shows delete confirmation dialog when delete button clicked', async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByText('Danger Zone')).toBeTruthy());

    const deleteButton = screen.getByRole('button', { name: /delete campaign/i });
    fireEvent.click(deleteButton);

    await waitFor(() => expect(screen.getByText('Delete Campaign?')).toBeTruthy());
    expect(screen.getByText(/permanently deleted/i)).toBeTruthy();
  });

  it('closes delete dialog when cancel clicked', async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByText('Danger Zone')).toBeTruthy());

    // Open delete dialog
    const deleteButton = screen.getByRole('button', { name: /delete campaign/i });
    fireEvent.click(deleteButton);

    await waitFor(() => expect(screen.getByText('Delete Campaign?')).toBeTruthy());

    // Click cancel
    const cancelButton = screen.getByRole('button', { name: /cancel/i });
    fireEvent.click(cancelButton);

    // Dialog should close
    await waitFor(() => expect(screen.queryByText('Delete Campaign?')).toBeFalsy());
  });

  it('cancels unit change confirmation dialog', async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByLabelText('Campaign Name')).toBeTruthy());

    // Change name to trigger confirmation
    const nameInput = screen.getByLabelText('Campaign Name');
    fireEvent.change(nameInput, { target: { value: 'Winter' } });

    const save = screen.getByRole('button', { name: /save changes/i });
    fireEvent.click(save);

    await waitFor(() => expect(screen.getByText('Confirm Changes to Shared Campaign')).toBeTruthy());

    // Click cancel
    const cancelButton = screen.getByRole('button', { name: /cancel/i });
    fireEvent.click(cancelButton);

    // Dialog should close
    await waitFor(() => expect(screen.queryByText('Confirm Changes to Shared Campaign')).toBeFalsy());
  });

  it("navigates to manage scout page when 'Manage Scout' button clicked", async () => {
    const mocks = createMocks();
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByText('Campaign Settings')).toBeTruthy());

    const manageButton = screen.getByRole('button', { name: /manage scout/i });
    fireEvent.click(manageButton);

    expect(mockNavigate).toHaveBeenCalledWith(`/scouts/${mockCampaign.profileId}/manage`);
  });

  it('saves changes when Save Anyway clicked on unit change confirmation', async () => {
    const dbCampaignId = `CAMPAIGN#${mockCampaign.campaignId}`;
    const dbProfileId = `PROFILE#${mockCampaign.profileId}`;
    const dbCatalogId = `CATALOG#${mockCampaign.catalogId}`;
    const mocks = [
      ...createMocks(),
      {
        request: {
          query: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: dbCampaignId,
              campaignName: 'Winter',
              startDate: '2025-09-01',
              endDate: '2025-12-01',
              catalogId: dbCatalogId,
            },
          },
        },
        result: {
          data: {
            updateCampaign: {
              ...mockCampaign,
              campaignId: dbCampaignId,
              profileId: dbProfileId,
              campaignName: 'Winter',
              catalog: {
                catalogId: mockCatalogs[0].catalogId,
                catalogName: mockCatalogs[0].catalogName,
                catalogType: mockCatalogs[0].catalogType,
                isDeleted: mockCatalogs[0].isDeleted,
              },
            },
          },
        },
      },
    ];
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByLabelText('Campaign Name')).toBeTruthy());

    // Change name to trigger confirmation
    const nameInput = screen.getByLabelText('Campaign Name');
    fireEvent.change(nameInput, { target: { value: 'Winter' } });

    const save = screen.getByRole('button', { name: /save changes/i });
    fireEvent.click(save);

    await waitFor(() => expect(screen.getByText('Confirm Changes to Shared Campaign')).toBeTruthy());

    // Click Save Anyway
    const saveAnywayButton = screen.getByRole('button', { name: /save anyway/i });
    fireEvent.click(saveAnywayButton);

    // Dialog should close after save
    await waitFor(() => expect(screen.queryByText('Confirm Changes to Shared Campaign')).toBeFalsy());
  });

  it('deletes campaign when Delete Permanently clicked', async () => {
    const dbCampaignId = `CAMPAIGN#${mockCampaign.campaignId}`;
    const mocks = [
      ...createMocks(),
      {
        request: { query: DELETE_CAMPAIGN, variables: { campaignId: dbCampaignId } },
        result: { data: { deleteCampaign: { campaignId: dbCampaignId } } },
      },
    ];
    renderWithMocks(mocks);

    await waitFor(() => expect(screen.getByText('Danger Zone')).toBeTruthy());

    // Open delete dialog
    const deleteButton = screen.getByRole('button', { name: /delete campaign/i });
    fireEvent.click(deleteButton);

    await waitFor(() => expect(screen.getByText('Delete Campaign?')).toBeTruthy());

    // Click Delete Permanently
    const deletePermanentlyButton = screen.getByRole('button', { name: /delete permanently/i });
    fireEvent.click(deletePermanentlyButton);

    // Should navigate back after deletion
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith(`/scouts/${mockCampaign.profileId}/manage`));
  });
});
