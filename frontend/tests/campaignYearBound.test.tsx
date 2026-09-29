/**
 * Regression test for issue #539.
 *
 * The campaign-year number input must be bounded the same way on both
 * campaign-creation surfaces, and that bound must actually stop a campaign
 * being created. The defect: CreateCampaignPage bounded the year to
 * `currentYear + 5` while CreateSharedCampaignPage hard-coded `max: 2100`, so
 * the same field accepted wildly different ranges depending on which page a
 * user was on.
 *
 * The bound is a fixed 2020..2050 range owned by `constants/campaign`, and both
 * forms must reject a year outside it at submit time - the number input's
 * `min`/`max` attributes are only advisory once a user types.
 *
 * These assertions are on observable behaviour: the `min`/`max` attributes of
 * the rendered inputs, and whether the create mutation actually runs.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { CreateCampaignPage } from '../src/pages/CreateCampaignPage';
import { CreateSharedCampaignPage } from '../src/pages/CreateSharedCampaignPage';
import {
  CREATE_SHARED_CAMPAIGN,
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  LIST_MY_PROFILES,
  LIST_MY_SHARED_CAMPAIGNS,
} from '../src/lib/graphql';

const CAMPAIGN_YEAR_MIN = 2020;
const CAMPAIGN_YEAR_MAX = 2050;

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

const CATALOG = {
  catalogId: 'catalog-1',
  catalogName: 'Test Catalog',
  catalogType: 'ADMIN_MANAGED',
  isActive: true,
  __typename: 'Catalog',
};

const PROFILE = {
  profileId: 'profile-1',
  sellerName: 'Scout Alpha',
  accountId: 'test-account-id',
  ownerAccountId: 'test-account-id',
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-01T00:00:00Z',
  isOwner: true,
  permissions: [],
  __typename: 'SellerProfile',
};

const CREATE_CAMPAIGN_MOCKS = [
  {
    request: { query: LIST_MY_PROFILES, variables: {} },
    result: { data: { listMyProfiles: { profiles: [PROFILE], nextToken: null } } },
  },
  { request: { query: LIST_MANAGED_CATALOGS, variables: {} }, result: { data: { listManagedCatalogs: [CATALOG] } } },
  { request: { query: LIST_MY_CATALOGS, variables: {} }, result: { data: { listMyCatalogs: [] } } },
];

const SHARED_CAMPAIGN_MOCKS = [
  { request: { query: LIST_MY_SHARED_CAMPAIGNS, variables: {} }, result: { data: { listMySharedCampaigns: [] } } },
  { request: { query: LIST_MANAGED_CATALOGS, variables: {} }, result: { data: { listManagedCatalogs: [CATALOG] } } },
  { request: { query: LIST_MY_CATALOGS, variables: {} }, result: { data: { listMyCatalogs: [] } } },
];

/** Mocks a successful create so the page navigates away when the submit runs. */
const createdSharedCampaignMock = (variables: { input: { campaignYear: number } }) => ({
  request: { query: CREATE_SHARED_CAMPAIGN, variables },
  result: {
    data: {
      createSharedCampaign: {
        __typename: 'SharedCampaign',
        sharedCampaignCode: 'code-1',
        catalogId: CATALOG.catalogId,
        catalog: { catalogId: CATALOG.catalogId, catalogName: CATALOG.catalogName },
        campaignName: 'Fall',
        campaignYear: variables.input.campaignYear,
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
        isActive: true,
        createdAt: '2024-01-01T00:00:00Z',
      },
    },
  },
});

const renderCreateCampaignPage = () =>
  render(
    <MockedProvider mocks={CREATE_CAMPAIGN_MOCKS}>
      <MemoryRouter initialEntries={['/create-campaign']}>
        <Routes>
          <Route path="/create-campaign" element={<CreateCampaignPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );

/** The shared page reads a preselected catalog from the router's location state. */
const renderSharedCampaignPage = (mocks: readonly MockedResponse[]) =>
  render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter initialEntries={[{ pathname: '/create-shared-campaign', state: { catalogId: CATALOG.catalogId } }]}>
        <Routes>
          <Route path="/create-shared-campaign" element={<CreateSharedCampaignPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );

/** Picks `option` from the MUI Select whose label is `label`. */
const selectOption = async (user: ReturnType<typeof userEvent.setup>, label: RegExp, option: RegExp | string) => {
  const labelNode = (await screen.findAllByText(label)).find((el) => el.tagName === 'LABEL') ?? screen.getByText(label);
  const combobox = (labelNode.closest('.MuiFormControl-root') as HTMLElement).querySelector(
    '[role="combobox"]',
  ) as HTMLElement;
  await user.click(combobox);
  await user.click(await screen.findByRole('option', { name: option }));
};

const setYear = async (user: ReturnType<typeof userEvent.setup>, label: RegExp, year: number) => {
  const input = screen.getByLabelText(label);
  await user.clear(input);
  await user.type(input, String(year));
};

describe('campaign-year bound (issue #539)', () => {
  it('renders the year input with the same 2020..2050 bounds on both campaign forms', async () => {
    const first = renderCreateCampaignPage();
    // MUI renders the required asterisk inside the label, so match by prefix.
    const ownCampaignYear = screen.getByLabelText(/^Year\b/) as HTMLInputElement;
    expect(ownCampaignYear).toHaveAttribute('min', String(CAMPAIGN_YEAR_MIN));
    expect(ownCampaignYear).toHaveAttribute('max', String(CAMPAIGN_YEAR_MAX));
    first.unmount();

    renderSharedCampaignPage(SHARED_CAMPAIGN_MOCKS);
    const sharedCampaignYear = screen.getByLabelText(/Campaign Year/) as HTMLInputElement;
    expect(sharedCampaignYear).toHaveAttribute('min', String(CAMPAIGN_YEAR_MIN));
    expect(sharedCampaignYear).toHaveAttribute('max', String(CAMPAIGN_YEAR_MAX));

    // The two forms must not be able to drift apart again.
    expect(sharedCampaignYear.getAttribute('max')).toBe(ownCampaignYear.getAttribute('max'));
    expect(sharedCampaignYear.getAttribute('min')).toBe(ownCampaignYear.getAttribute('min'));
  });

  it('creates a shared campaign dated 2050', async () => {
    const user = userEvent.setup({ delay: null });
    const variables = {
      input: {
        catalogId: CATALOG.catalogId,
        campaignName: 'Fall',
        campaignYear: CAMPAIGN_YEAR_MAX,
        unitType: 'Pack',
        unitNumber: 42,
        city: 'Austin',
        state: 'TX',
      },
    };
    renderSharedCampaignPage([...SHARED_CAMPAIGN_MOCKS, createdSharedCampaignMock(variables)]);

    fireEvent.change(screen.getByLabelText(/Campaign Name/), { target: { value: 'Fall' } });
    await setYear(user, /Campaign Year/, CAMPAIGN_YEAR_MAX);
    await selectOption(user, /Unit Type/, 'Pack');
    fireEvent.change(screen.getByLabelText(/Unit Number/), { target: { value: '42' } });
    fireEvent.change(screen.getByLabelText(/City/), { target: { value: 'Austin' } });
    await selectOption(user, /^State/, 'TX');

    const submit = screen.getByRole('button', { name: /Create Shared Campaign/ });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    // Navigating to the campaign list is what a successful mutation does here.
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/shared-campaigns'));
  });

  it('refuses to create a shared campaign dated past 2050', async () => {
    const user = userEvent.setup({ delay: null });
    // No create mutation is mocked: if the form submitted anyway, Apollo would
    // error instead of the page showing its own out-of-range message.
    renderSharedCampaignPage(SHARED_CAMPAIGN_MOCKS);

    fireEvent.change(screen.getByLabelText(/Campaign Name/), { target: { value: 'Fall' } });
    await setYear(user, /Campaign Year/, 2051);
    await selectOption(user, /Unit Type/, 'Pack');
    fireEvent.change(screen.getByLabelText(/Unit Number/), { target: { value: '42' } });
    fireEvent.change(screen.getByLabelText(/City/), { target: { value: 'Austin' } });
    await selectOption(user, /^State/, 'TX');

    const submit = screen.getByRole('button', { name: /Create Shared Campaign/ });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    const alert = await screen.findByText('Campaign year must be between 2020 and 2050');
    expect(alert).toBeInTheDocument();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('refuses to create an own campaign dated past 2050', async () => {
    const user = userEvent.setup({ delay: null });
    // No create mutation is mocked: if the form submitted anyway, Apollo would
    // report the missing mock instead of the page showing its own message.
    renderCreateCampaignPage();

    await selectOption(user, /Select Profile/, /Scout Alpha/);
    fireEvent.change(screen.getByLabelText(/Campaign Name/), { target: { value: 'Fall' } });
    await selectOption(user, /Select Catalog/, CATALOG.catalogName);
    await setYear(user, /^Year\b/, 2051);

    const submit = screen.getByRole('button', { name: /Create Campaign/ });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    expect(await screen.findByText('Campaign year must be between 2020 and 2050')).toBeInTheDocument();
    expect(mockNavigate).not.toHaveBeenCalled();
  });
}, 30000); // MUI Select interactions are slow under a loaded parallel run
