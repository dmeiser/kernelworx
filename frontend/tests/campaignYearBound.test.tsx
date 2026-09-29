/**
 * Regression test for issue #539.
 *
 * The campaign-year number input must be bounded the same way on both
 * campaign-creation surfaces. The defect: CreateCampaignPage bounded the year
 * to `currentYear + 5`, while CreateSharedCampaignPage hard-coded `max: 2100`,
 * so the same field accepted wildly different ranges depending on which page
 * a user was on. The intended rule is `min: 2020`, `max: currentYear + 5`.
 *
 * This test reproduces the defect: before the fix the shared-campaign page's
 * year input rendered `max: 2100` and the test failed; after the fix both
 * pages render `max: String(currentYear + 5)` and the test passes.
 *
 * It asserts observable DOM behavior (the `min`/`max` attributes on the
 * rendered number inputs), not the source text.
 */

import { render, screen } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { CreateCampaignPage } from '../src/pages/CreateCampaignPage';
import { CreateSharedCampaignPage } from '../src/pages/CreateSharedCampaignPage';
import {
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  LIST_MY_PROFILES,
  LIST_MY_SHARED_CAMPAIGNS,
} from '../src/lib/graphql';

// Preserve the real router (MemoryRouter supplies useParams/useLocation); only
// override useNavigate so navigation side effects are inert during render.
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

// Auth and toasts are not under test here; stub them out so the pages render.
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({
    isAuthenticated: true,
    isLoading: false,
    account: { accountId: 'test-account-id', email: 'test@example.com' },
  })),
}));
vi.mock('../src/components/Toast', () => ({
  useToast: vi.fn(() => ({ showSuccess: vi.fn(), showError: vi.fn() })),
}));

const CURRENT_YEAR = new Date().getFullYear();

const EMPTY_CATALOG_MOCKS = [
  {
    request: { query: LIST_MANAGED_CATALOGS, variables: {} },
    result: { data: { listManagedCatalogs: [] }, delay: 0 },
  },
  {
    request: { query: LIST_MY_CATALOGS, variables: {} },
    result: { data: { listMyCatalogs: [] }, delay: 0 },
  },
];

/** Mocks so the shared-campaign page's useQuery hooks settle deterministically. */
const SHARED_CAMPAIGN_MOCKS = [
  {
    request: { query: LIST_MY_SHARED_CAMPAIGNS, variables: {} },
    result: { data: { listMySharedCampaigns: [] }, delay: 0 },
  }];

describe('campaign-year bound (issue #539)', () => {
  it('bounds the year to min 2020 and max currentYear + 5 on the Create Campaign page', () => {
    const mocks = [
      {
        request: { query: LIST_MY_PROFILES, variables: {} },
        result: {
          data: {
            listMyProfiles: {
              profiles: [
                {
                  profileId: 'profile-1',
                  sellerName: 'Scout Alpha',
                  accountId: 'test-account-id',
                  ownerAccountId: 'test-account-id',
                  createdAt: '2024-01-01T00:00:00Z',
                  updatedAt: '2024-01-01T00:00:00Z',
                  isOwner: true,
                  permissions: [],
                  __typename: 'SellerProfile',
                },
              ],
              nextToken: null,
            },
          },
          delay: 0,
        },
      },
      ...EMPTY_CATALOG_MOCKS,
    ];

    render(
      <MockedProvider mocks={mocks} >
        <MemoryRouter initialEntries={['/create-campaign']}>
          <Routes>
            <Route path="/create-campaign" element={<CreateCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    // MUI renders the required asterisk inside the label, so match by prefix.
    const yearInput = screen.getByLabelText(/^Year\b/) as HTMLInputElement;
    expect(yearInput).toHaveAttribute('min', '2020');
    expect(yearInput).toHaveAttribute('max', String(CURRENT_YEAR + 5));
  });

  it('bounds the year to min 2020 and max currentYear + 5 on the Create Shared Campaign page', () => {
    render(
      <MockedProvider mocks={SHARED_CAMPAIGN_MOCKS} >
        <MemoryRouter initialEntries={['/create-shared-campaign']}>
          <Routes>
            <Route path="/create-shared-campaign" element={<CreateSharedCampaignPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    const yearInput = screen.getByLabelText(/Campaign Year/) as HTMLInputElement;
    expect(yearInput).toHaveAttribute('min', '2020');
    expect(yearInput).toHaveAttribute('max', String(CURRENT_YEAR + 5));
  });
});
