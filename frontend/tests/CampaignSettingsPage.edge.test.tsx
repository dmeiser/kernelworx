/**
 * CampaignSettingsPage edge-case tests that require a stubbed useParams.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CampaignSettingsPage } from '../src/pages/CampaignSettingsPage';
import { LIST_MANAGED_CATALOGS, LIST_MY_CATALOGS } from '../src/lib/graphql';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useParams: () => ({ profileId: 'profile-123' }),
  };
});

const mockCatalogs = [
  {
    __typename: 'Catalog',
    catalogId: 'CATALOG#catalog-1',
    catalogName: 'Official Catalog',
    catalogType: 'ADMIN_MANAGED',
    isPublic: true,
    isDeleted: false,
    products: [],
  },
];

const mocks = [
  {
    request: { query: LIST_MANAGED_CATALOGS },
    result: { data: { listManagedCatalogs: mockCatalogs } },
  },
  {
    request: { query: LIST_MY_CATALOGS },
    result: { data: { listMyCatalogs: [] } },
  },
];

const renderPage = () =>
  render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <MemoryRouter initialEntries={['/scouts/profile-123/campaigns/campaign-456/settings']}>
        <Routes>
          <Route path="/scouts/:profileId/campaigns/:campaignId/settings" element={<CampaignSettingsPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );

describe('CampaignSettingsPage edge cases', () => {
  it('skips campaign query and renders when campaignId is missing', async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Campaign Settings')).toBeInTheDocument();
    });

    expect(screen.getByRole('combobox', { name: /product catalog/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
  });

  it('does not delete when campaignId is missing', async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Campaign Settings')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /delete campaign/i }));

    await waitFor(() => {
      expect(screen.getByText('Delete Campaign?')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /delete permanently/i }));

    // Dialog stays open because the delete handler returns early with no campaignId
    expect(screen.getByText('Delete Campaign?')).toBeInTheDocument();
  });
});
