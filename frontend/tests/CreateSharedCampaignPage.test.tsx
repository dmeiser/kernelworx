/**
 * Behavioural tests for CreateSharedCampaignPage.
 *
 * This page was previously untested, so importing it for the campaign-year
 * regression test brought it into the coverage report at 60%. These tests
 * cover the paths a user actually takes through the form: the rejection paths
 * that must not create anything, the optional fields the mutation carries, the
 * active-campaign ceiling, and the two ways back out of the page.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CreateSharedCampaignPage } from '../src/pages/CreateSharedCampaignPage';
import {
  CREATE_SHARED_CAMPAIGN,
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  LIST_MY_SHARED_CAMPAIGNS,
} from '../src/lib/graphql';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({
    isAuthenticated: true,
    isLoading: false,
    account: { accountId: 'test-account-id', email: 'test@example.com' },
  })),
}));

const CATALOG = {
  __typename: 'Catalog',
  catalogId: 'catalog-1',
  catalogName: 'Official Popcorn',
  catalogType: 'ADMIN_MANAGED',
  isActive: true,
};

const sharedCampaign = (code: string, isActive = true) => ({
  __typename: 'SharedCampaign',
  sharedCampaignCode: code,
  catalogId: CATALOG.catalogId,
  catalog: { __typename: 'Catalog', catalogId: CATALOG.catalogId, catalogName: CATALOG.catalogName },
  campaignName: 'Fall',
  campaignYear: 2026,
  startDate: null,
  endDate: null,
  unitType: 'Pack',
  unitNumber: 42,
  city: 'Austin',
  state: 'TX',
  createdBy: 'test-account-id',
  createdByName: 'Scout Alpha',
  creatorMessage: '',
  description: null,
  isActive,
  createdAt: '2024-01-01T00:00:00Z',
});

const baseMocks = (sharedCampaigns: unknown[] = []): MockedResponse[] => [
  {
    request: { query: LIST_MY_SHARED_CAMPAIGNS, variables: {} },
    result: { data: { listMySharedCampaigns: sharedCampaigns } },
  },
  { request: { query: LIST_MANAGED_CATALOGS, variables: {} }, result: { data: { listManagedCatalogs: [CATALOG] } } },
  { request: { query: LIST_MY_CATALOGS, variables: {} }, result: { data: { listMyCatalogs: [] } } },
];

const createdMock: MockedResponse = {
  request: {
    query: CREATE_SHARED_CAMPAIGN,
    variables: {
      input: {
        catalogId: CATALOG.catalogId,
        campaignName: 'Fall',
        campaignYear: 2026,
        startDate: '2026-08-01',
        endDate: '2026-10-31',
        unitType: 'Pack',
        unitNumber: 42,
        city: 'Austin',
        state: 'TX',
        creatorMessage: 'Thanks for helping!',
        description: 'Pack 42 fall fundraiser',
      },
    },
  },
  result: { data: { createSharedCampaign: sharedCampaign('NEWCODE') } },
};

const renderPage = (mocks: readonly MockedResponse[], catalogId: string | undefined = CATALOG.catalogId) =>
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[{ pathname: '/create-shared-campaign', state: catalogId ? { catalogId } : {} }]}>
        <Routes>
          <Route path="/create-shared-campaign" element={<CreateSharedCampaignPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );

/** Fills every required field, leaving `skip` empty. */
const fillRequiredFields = async (user: ReturnType<typeof userEvent.setup>, skip?: 'city') => {
  fireEvent.change(screen.getByLabelText(/Campaign Name/), { target: { value: 'Fall' } });
  fireEvent.change(screen.getByLabelText(/Unit Number/), { target: { value: '42' } });
  if (skip !== 'city') {
    fireEvent.change(screen.getByLabelText(/City/), { target: { value: 'Austin' } });
  }
  const stateLabel = (await screen.findAllByText(/^State/)).find((el) => el.tagName === 'LABEL');
  const stateCombo = (stateLabel?.closest('.MuiFormControl-root') as HTMLElement).querySelector(
    '[role="combobox"]',
  ) as HTMLElement;
  await user.click(stateCombo);
  await user.click(await screen.findByRole('option', { name: 'TX' }));
};

const pickUnitType = async (user: ReturnType<typeof userEvent.setup>) => {
  const unitLabel = (await screen.findAllByText(/Unit Type/)).find((el) => el.tagName === 'LABEL');
  const unitCombo = (unitLabel?.closest('.MuiFormControl-root') as HTMLElement).querySelector(
    '[role="combobox"]',
  ) as HTMLElement;
  await user.click(unitCombo);
  await user.click(await screen.findByRole('option', { name: 'Pack' }));
};

const pickCatalog = async (user: ReturnType<typeof userEvent.setup>) => {
  const label = (await screen.findAllByText(/Select Catalog/)).find((el) => el.tagName === 'LABEL');
  const combo = (label?.closest('.MuiFormControl-root') as HTMLElement).querySelector(
    '[role="combobox"]',
  ) as HTMLElement;
  await waitFor(() => expect(combo).not.toHaveAttribute('aria-disabled', 'true'));
  await user.click(combo);
  await user.click(await screen.findByRole('option', { name: CATALOG.catalogName }));
};

const submit = () => screen.getByRole('button', { name: /Create Shared Campaign/ });

describe('CreateSharedCampaignPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates the campaign with the optional fields it collected', async () => {
    const user = userEvent.setup({ delay: null });
    renderPage([...baseMocks(), createdMock], undefined);

    await pickCatalog(user);
    await fillRequiredFields(user);
    await pickUnitType(user);
    fireEvent.change(screen.getByLabelText(/Start Date/), { target: { value: '2026-08-01' } });
    fireEvent.change(screen.getByLabelText(/End Date/), { target: { value: '2026-10-31' } });
    fireEvent.change(screen.getByLabelText(/Message to Scouts/), { target: { value: 'Thanks for helping!' } });
    fireEvent.change(screen.getByLabelText(/Description/), { target: { value: 'Pack 42 fall fundraiser' } });

    await waitFor(() => expect(submit()).toBeEnabled());
    await user.click(submit());

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/shared-campaigns'));
  });

  it('shows the failure when the create mutation errors', async () => {
    const user = userEvent.setup({ delay: null });
    renderPage([...baseMocks(), { request: createdMock.request, error: new Error('Catalog is no longer active') }]);

    await fillRequiredFields(user);
    await pickUnitType(user);
    fireEvent.change(screen.getByLabelText(/Start Date/), { target: { value: '2026-08-01' } });
    fireEvent.change(screen.getByLabelText(/End Date/), { target: { value: '2026-10-31' } });
    fireEvent.change(screen.getByLabelText(/Message to Scouts/), { target: { value: 'Thanks for helping!' } });
    fireEvent.change(screen.getByLabelText(/Description/), { target: { value: 'Pack 42 fall fundraiser' } });

    await waitFor(() => expect(submit()).toBeEnabled());
    await user.click(submit());

    expect(await screen.findByText('Catalog is no longer active')).toBeInTheDocument();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('refuses to create once the active shared-campaign limit is reached', async () => {
    const user = userEvent.setup({ delay: null });
    const atLimit = Array.from({ length: 50 }, (_, i) => sharedCampaign(`CODE${i}`));
    renderPage(baseMocks(atLimit));

    expect(await screen.findByText(/reached the maximum of 50 active shared campaigns/)).toBeInTheDocument();

    await fillRequiredFields(user);
    await pickUnitType(user);
    await waitFor(() => expect(submit()).toBeDisabled());
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('hides a public catalog the account already owns as a personal catalog', async () => {
    const user = userEvent.setup({ delay: null });
    renderPage(
      [
        {
          request: { query: LIST_MY_SHARED_CAMPAIGNS, variables: {} },
          result: { data: { listMySharedCampaigns: [] } },
        },
        {
          request: { query: LIST_MANAGED_CATALOGS, variables: {} },
          result: { data: { listManagedCatalogs: [CATALOG] } },
        },
        {
          request: { query: LIST_MY_CATALOGS, variables: {} },
          result: { data: { listMyCatalogs: [{ ...CATALOG, catalogName: 'My Popcorn' }] } },
        },
      ],
      undefined,
    );

    const catalogLabel = (await screen.findAllByText(/Select Catalog/)).find((el) => el.tagName === 'LABEL');
    const catalogCombo = (catalogLabel?.closest('.MuiFormControl-root') as HTMLElement).querySelector(
      '[role="combobox"]',
    ) as HTMLElement;
    await waitFor(() => expect(catalogCombo).not.toHaveAttribute('aria-disabled', 'true'));
    await user.click(catalogCombo);

    // The duplicate is listed once, under "My Catalogs" rather than "Public Catalogs".
    expect(await screen.findByRole('option', { name: 'My Popcorn' })).toBeInTheDocument();
    expect(screen.queryByText('Public Catalogs')).not.toBeInTheDocument();
  });

  it('leaves the page without creating anything from the back and cancel buttons', async () => {
    const user = userEvent.setup({ delay: null });
    renderPage(baseMocks());

    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(mockNavigate).toHaveBeenCalledWith(-1);

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(mockNavigate).toHaveBeenCalledWith(-1);
  });
}, 30000); // MUI Select interactions are slow under a loaded parallel run
