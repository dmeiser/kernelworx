import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { vi } from 'vitest';
import {
  UNIT_CAMPAIGNS,
  UNIT_CAMPAIGN_CATALOG,
  UNIT_CAMPAIGN_ROSTER,
  REMOVE_UNIT_CAMPAIGN_MEMBERSHIP,
  LIST_MY_CATALOGS,
  LIST_MANAGED_CATALOGS,
} from '../src/lib/graphql';
import UnitCampaignsSection from '../src/pages/UnitCampaignsSection';

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    account: { accountId: 'self', email: 'self@fixtures.kernelworx.test', givenName: 'Self' },
    loading: false,
    isAuthenticated: true,
    isAdmin: false,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const PAGE_INFO = { __typename: 'PageInfo', endCursor: null, hasNextPage: false };
const UNIT_ID = 'unit-1';
const match = () => true;

const campaign = (over: Record<string, unknown> = {}) => ({
  __typename: 'UnitCampaignAdmin',
  unitCampaignId: 'uc-1',
  unitId: UNIT_ID,
  campaignName: 'Pack 3149 Fall Show & Sell',
  campaignYear: 2026,
  catalogId: 'cat-1',
  joinCode: 'JOIN-123',
  isActive: true,
  version: 1,
  createdAt: '2026-11-01T00:00:00+00:00',
  updatedAt: '2026-11-01T00:00:00+00:00',
  createdByAccountId: 'self',
  updatedByAccountId: 'self',
  ...over,
});

const membership = (over: Record<string, unknown> = {}) => ({
  __typename: 'UnitCampaignMembership',
  campaignId: 'camp-participant',
  profileId: 'prof-participant',
  unitCampaignId: 'uc-1',
  unitId: UNIT_ID,
  status: 'ACTIVE',
  joinedAt: '2026-11-02T00:00:00+00:00',
  removedAt: null,
  joinedByAccountId: 'self',
  removedByAccountId: null,
  version: 1,
  ...over,
});

const catalogResult = {
  data: {
    unitCampaignCatalog: {
      __typename: 'UnitCampaignCatalog',
      catalogId: 'cat-1',
      catalogName: 'Fall 2026 Show & Sell',
      products: [],
    },
  },
};

function renderSection(mocks: unknown[]) {
  return render(
    <MockedProvider mocks={mocks as never} defaultOptions={{ watchQuery: { fetchPolicy: 'no-cache' } }}>
      <UnitCampaignsSection unitId={UNIT_ID} />
    </MockedProvider>,
  );
}

it('shows the empty state when the unit has no campaigns', async () => {
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: { data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [], pageInfo: PAGE_INFO } } },
    },
  ]);

  expect(await screen.findByText(/No campaigns yet/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Create campaign/i })).toBeInTheDocument();
});

it('selects a campaign and shows its join code, catalog, and roster', async () => {
  const user = userEvent.setup();
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: {
        data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [campaign()], pageInfo: PAGE_INFO } },
      },
    },
    { request: { query: UNIT_CAMPAIGN_CATALOG, variables: match }, result: catalogResult },
    {
      request: { query: UNIT_CAMPAIGN_ROSTER, variables: match },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [membership()],
            pageInfo: PAGE_INFO,
          },
        },
      },
    },
  ]);

  const row = await screen.findByText(/Pack 3149 Fall Show & Sell \(2026\)/i);
  await user.click(row);

  expect(await screen.findByTestId('join-code-display')).toHaveTextContent('JOIN-123');
  await screen.findByText(/Fall 2026 Show & Sell/i);
  expect(screen.getByTestId('catalog-display')).toHaveTextContent('Fall 2026 Show & Sell');
  await screen.findByTestId('remove-membership');
});

it('confirms before removing a roster member, then closes on success', async () => {
  const user = userEvent.setup();
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: {
        data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [campaign()], pageInfo: PAGE_INFO } },
      },
    },
    { request: { query: UNIT_CAMPAIGN_CATALOG, variables: match }, result: catalogResult },
    {
      request: { query: UNIT_CAMPAIGN_ROSTER, variables: match },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [membership()],
            pageInfo: PAGE_INFO,
          },
        },
      },
    },
    {
      request: { query: REMOVE_UNIT_CAMPAIGN_MEMBERSHIP, variables: match },
      result: {
        data: {
          removeUnitCampaignMembership: {
            __typename: 'UnitCampaignMembership',
            campaignId: 'camp-participant',
            profileId: 'prof-participant',
            status: 'REMOVED',
            removedAt: '2026-11-05T00:00:00+00:00',
            version: 2,
          },
        },
      },
    },
    {
      request: { query: UNIT_CAMPAIGN_ROSTER, variables: match },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [membership({ status: 'REMOVED', removedAt: '2026-11-05T00:00:00+00:00', version: 2 })],
            pageInfo: PAGE_INFO,
          },
        },
      },
    },
  ]);

  const row = await screen.findByText(/Pack 3149 Fall Show & Sell \(2026\)/i);
  await user.click(row);
  await user.click(await screen.findByTestId('remove-membership'));

  await screen.findByText('Remove this Scout from the roster?');
  const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' });
  await user.click(confirm);

  await waitFor(() => expect(screen.queryByText('Remove this Scout from the roster?')).not.toBeInTheDocument());
});

it('validates the create form before submitting', async () => {
  const user = userEvent.setup();
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: {
        data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [campaign()], pageInfo: PAGE_INFO } },
      },
    },
    { request: { query: LIST_MY_CATALOGS, variables: match }, result: { data: { listMyCatalogs: [] } } },
    { request: { query: LIST_MANAGED_CATALOGS, variables: match }, result: { data: { listManagedCatalogs: [] } } },
  ]);

  await user.click(await screen.findByRole('button', { name: /Create campaign/i }));
  const dialog = await screen.findByRole('dialog');
  const submit = await within(dialog).findByRole('button', { name: /Create campaign/i });
  await user.click(submit);

  expect(await screen.findByText(/Enter a campaign name, year, and choose a catalog/i)).toBeInTheDocument();
});

it('keeps removed roster memberships as history (REMOVED status)', async () => {
  const user = userEvent.setup();
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: {
        data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [campaign()], pageInfo: PAGE_INFO } },
      },
    },
    { request: { query: UNIT_CAMPAIGN_CATALOG, variables: match }, result: catalogResult },
    {
      request: { query: UNIT_CAMPAIGN_ROSTER, variables: match },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [
              membership({
                campaignId: 'camp-prev',
                profileId: 'prof-prev',
                status: 'REMOVED',
                removedAt: '2026-11-05T00:00:00+00:00',
                version: 2,
              }),
            ],
            pageInfo: PAGE_INFO,
          },
        },
      },
    },
  ]);

  const row = await screen.findByText(/Pack 3149 Fall Show & Sell \(2026\)/i);
  await user.click(row);

  expect(await screen.findByText('Removed')).toBeInTheDocument();
});

it('fixes the catalog when editing (immutable after creation)', async () => {
  const user = userEvent.setup();
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: {
        data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [campaign()], pageInfo: PAGE_INFO } },
      },
    },
    { request: { query: UNIT_CAMPAIGN_CATALOG, variables: match }, result: catalogResult },
    {
      request: { query: UNIT_CAMPAIGN_ROSTER, variables: match },
      result: {
        data: {
          unitCampaignRoster: { __typename: 'UnitCampaignMembershipConnection', items: [], pageInfo: PAGE_INFO },
        },
      },
    },
  ]);

  const row = await screen.findByText(/Pack 3149 Fall Show & Sell \(2026\)/i);
  await user.click(row);
  await user.click(await screen.findByTestId('edit-campaign-button'));

  expect(await screen.findByTestId('edit-catalog-immutable-note')).toBeInTheDocument();
});

it('surfaces a catalog load failure with a working Retry instead of a silent placeholder', async () => {
  const user = userEvent.setup();
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: {
        data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [campaign()], pageInfo: PAGE_INFO } },
      },
    },
    {
      request: { query: UNIT_CAMPAIGN_CATALOG, variables: match },
      result: {
        errors: [new GraphQLError('The catalog is unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })],
      },
    },
    { request: { query: UNIT_CAMPAIGN_CATALOG, variables: match }, result: catalogResult },
    {
      request: { query: UNIT_CAMPAIGN_ROSTER, variables: match },
      result: {
        data: {
          unitCampaignRoster: { __typename: 'UnitCampaignMembershipConnection', items: [], pageInfo: PAGE_INFO },
        },
      },
    },
  ]);

  const row = await screen.findByText(/Pack 3149 Fall Show & Sell \(2026\)/i);
  await user.click(row);

  expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to load the catalog/i);

  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText(/Fall 2026 Show & Sell/i)).toBeInTheDocument();
});

it('surfaces create-catalog list failures with a working Retry and never blames the user', async () => {
  const user = userEvent.setup();
  renderSection([
    {
      request: { query: UNIT_CAMPAIGNS, variables: match },
      result: {
        data: { unitCampaigns: { __typename: 'UnitCampaignConnection', items: [campaign()], pageInfo: PAGE_INFO } },
      },
    },
    // Both catalog list queries fail on the initial load.
    {
      request: { query: LIST_MY_CATALOGS, variables: match },
      result: {
        errors: [new GraphQLError('The catalogs are unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })],
      },
    },
    {
      request: { query: LIST_MANAGED_CATALOGS, variables: match },
      result: {
        errors: [new GraphQLError('The catalogs are unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })],
      },
    },
    // Retry recovers both.
    { request: { query: LIST_MY_CATALOGS, variables: match }, result: { data: { listMyCatalogs: [] } } },
    { request: { query: LIST_MANAGED_CATALOGS, variables: match }, result: { data: { listManagedCatalogs: [] } } },
  ]);
  await user.click(await screen.findByRole('button', { name: /Create campaign/i }));
  const dialog = await screen.findByRole('dialog');

  // A failed catalog read is an error + Retry, not a silent empty list and not a user-blame on submit.
  expect(await screen.findByText(/Unable to load the catalogs/i)).toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: /^Create campaign$/i })).toBeDisabled();
  expect(screen.queryByText(/choose a catalog/i)).not.toBeInTheDocument();

  // Retry re-runs both queries; wait for them to settle (loading -> data) so the form re-enables.
  await user.click(screen.getByRole('button', { name: /^Retry$/i }));
  await waitFor(() => expect(within(dialog).getByRole('button', { name: /^Create campaign$/i })).toBeEnabled());
  expect(screen.queryByText(/Unable to load the catalogs/i)).not.toBeInTheDocument();
});
