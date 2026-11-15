/**
 * Unit Campaign list and creation (§1.6.3) — including the catalog-change
 * rejection the checklist names.
 *
 * A campaign's catalog is chosen once, because inventory, Order origin, and event
 * product identity all key on it. So this screen offers no way to send an existing
 * campaign to another catalog, and says why at the moment the choice is made.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { UnitCampaignsPanel } from '../src/components/UnitCampaignsPanel';
import { CREATE_UNIT_CAMPAIGN, LIST_MY_CATALOGS, LIST_UNIT_CAMPAIGNS, LIST_MANAGED_CATALOGS, UPDATE_UNIT_CAMPAIGN } from '../src/lib/graphql';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { GraphQLError } from 'graphql';
import { campaignFixture, unitFixture } from './helpers/unitFixtures';
import { chooseOptionByName, typeInto } from './helpers/unitUi';

const UNIT_ID = 'UNIT#pack-3149';
const CAMPAIGN_ID = 'UNITCAMP#pack-3149-fall';
const YEAR = new Date().getFullYear();

const navigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => navigate };
});

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function campaignsQuery(items: unknown[], isActive?: boolean) {
  return {
    request: { query: LIST_UNIT_CAMPAIGNS, variables: { unitId: UNIT_ID, isActive, page: { limit: UNIT_PAGE_SIZE } } },
    result: {
      data: {
        unitCampaigns: {
          __typename: 'UnitCampaignConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

const catalogMock = {
  __typename: 'Catalog',
  catalogId: 'CATALOG#popcorn-2026',
  catalogName: 'Popcorn 2026',
  catalogType: 'USER_CREATED',
  isPublic: false,
  isDeleted: false,
  products: [],
};

function renderPanel(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      <MemoryRouter>
        <UnitCampaignsPanel unit={unitFixture()} />
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('UnitCampaignsPanel', () => {
  it('lists a campaign with its status, hidden join code, and the catalog it is fixed to', async () => {
    renderPanel([campaignsQuery([campaignFixture()])]);

    const row = await screen.findByTestId(`campaign-row-${CAMPAIGN_ID}`);
    expect(within(row).getByTestId(`campaign-status-${CAMPAIGN_ID}`)).toHaveTextContent('Active');
    expect(within(row).getByTestId(`catalog-${CAMPAIGN_ID}`)).toHaveTextContent('CATALOG#popcorn-2026');
    expect(within(row).getByTestId(`join-code-${CAMPAIGN_ID}`)).toHaveTextContent('••••••••••••••••');

    await userEvent.setup().click(within(row).getByTestId(`reveal-${CAMPAIGN_ID}`));
    expect(within(row).getByTestId(`join-code-${CAMPAIGN_ID}`)).toHaveTextContent('JOIN1234CODE5678');
  });

  it('offers no way to change an existing campaign’s catalog, and says the catalog is fixed at creation', async () => {
    renderPanel([campaignsQuery([campaignFixture()])]);

    const row = await screen.findByTestId(`campaign-row-${CAMPAIGN_ID}`);
    // The row's controls are the join-code reveal, the roster link, and open/close.
    // Nothing on this row sends the campaign to a different catalog.
    expect(within(row).queryAllByRole('combobox')).toHaveLength(0);
    expect(within(row).queryAllByRole('textbox')).toHaveLength(0);
    expect(within(row).getByTestId(`catalog-${CAMPAIGN_ID}`)).toHaveTextContent('CATALOG#popcorn-2026');

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('create-campaign'));
    expect(
      await screen.findByText(/The catalog is fixed once the campaign exists/),
    ).toBeInTheDocument();
  });

  it('closing a campaign writes only isActive, against the version that row carried', async () => {
    const campaign = campaignFixture();
    const closed = { ...campaign, isActive: false, version: 2 };
    const mocks = [
      campaignsQuery([campaign]),
      {
        request: {
          query: UPDATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              isActive: false,
              version: { expectedVersion: 1 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { updateUnitCampaign: closed } },
      },
      campaignsQuery([closed]),
    ];
    renderPanel(mocks);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId(`toggle-${CAMPAIGN_ID}`));
    await user.click(await screen.findByRole('button', { name: 'Close campaign' }));

    await waitFor(() => expect(screen.getByTestId(`campaign-status-${CAMPAIGN_ID}`)).toHaveTextContent('Closed'));
    expect(screen.queryAllByRole('alert')).toHaveLength(0);
  });

  it('creates a campaign against a chosen catalog and answers its join code once', async () => {
    const created = campaignFixture();
    const mocks = [
      campaignsQuery([]),
      { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [catalogMock] } } },
      { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: [] } } },
      {
        request: {
          query: CREATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitId: UNIT_ID,
              campaignName: 'Fall Popcorn',
              campaignYear: YEAR,
              catalogId: catalogMock.catalogId,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { createUnitCampaign: created } },
      },
      campaignsQuery([created]),
    ];
    renderPanel(mocks);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('create-campaign'));
    await typeInto('campaign-name', 'Fall Popcorn', user);
    await chooseOptionByName('Catalog *', 'Popcorn 2026', user);
    await user.click(await screen.findByTestId('form-dialog-confirm'));

    expect(await screen.findByTestId('created-join-code')).toHaveTextContent('JOIN1234CODE5678');
    expect(await screen.findByTestId(`campaign-row-${CAMPAIGN_ID}`)).toBeInTheDocument();
  });


  it('re-reads the list with the status the filter names', async () => {
    const campaign = campaignFixture();
    const closed = { ...campaign, isActive: false };
    const mocks = [
      campaignsQuery([campaign]),
      campaignsQuery([closed], true),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await chooseOptionByName('Show', 'Active only', user);

    expect(await screen.findByTestId(`campaign-status-${CAMPAIGN_ID}`)).toHaveTextContent('Closed');
  });

  it('a campaign read that failed is not shown as an empty list', async () => {
    renderPanel([{ request: { query: LIST_UNIT_CAMPAIGNS, variables: { unitId: UNIT_ID, isActive: undefined, page: { limit: UNIT_PAGE_SIZE } } }, error: new GraphQLError('offline') }]);

    expect(await screen.findByText("Could not load this Unit's campaigns.")).toBeInTheDocument();
  });

  it('a refused close says why and leaves the row open', async () => {
    const campaign = campaignFixture();
    const mocks = [
      campaignsQuery([campaign]),
      {
        request: {
          query: UPDATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              isActive: false,
              version: { expectedVersion: 1 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('This campaign is mid-event.', { extensions: { code: 'CONFLICT' } }),
      },
      campaignsQuery([campaign]),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`toggle-${CAMPAIGN_ID}`));
    await user.click(await screen.findByRole('button', { name: 'Close campaign' }));

    expect(await screen.findByText('This campaign is mid-event.')).toBeInTheDocument();
    expect(await screen.findByTestId(`campaign-status-${CAMPAIGN_ID}`)).toHaveTextContent('Active');
  });

  it('opening a closed campaign is offered as the opposite action', async () => {
    const closed = campaignFixture({ isActive: false });
    const reopened = { ...closed, isActive: true, version: 2 };
    const mocks = [
      campaignsQuery([closed]),
      {
        request: {
          query: UPDATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              isActive: true,
              version: { expectedVersion: 2 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { updateUnitCampaign: reopened } },
      },
      campaignsQuery([reopened]),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`toggle-${CAMPAIGN_ID}`));
    expect(await screen.findByText('Opening lets Scouts with the join code participate again. Nothing else changes.')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Open campaign' }));

    await waitFor(() => expect(screen.getByTestId(`campaign-status-${CAMPAIGN_ID}`)).toHaveTextContent('Active'));
  });

  it('refuses an unfinished campaign form and names what is missing', async () => {
    renderPanel([
      campaignsQuery([]),
      { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [catalogMock] } } },
      { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: [] } } },
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-campaign'));
    await user.click(await screen.findByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Give the campaign a name.')).toBeInTheDocument();

    await typeInto('campaign-name', 'Fall Popcorn', user);
    await user.click(await screen.findByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Choose the catalog this campaign sells from.')).toBeInTheDocument();
  });

  it('a campaign the server will not create says why, and the note dismisses', async () => {
    renderPanel([
      campaignsQuery([]),
      { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [catalogMock] } } },
      { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: [] } } },
      {
        request: {
          query: CREATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitId: UNIT_ID,
              campaignName: 'Fall Popcorn',
              campaignYear: YEAR,
              catalogId: catalogMock.catalogId,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('That catalog is not yours to use.', { extensions: { code: 'FORBIDDEN' } }),
      },
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-campaign'));
    await typeInto('campaign-name', 'Fall Popcorn', user);
    await chooseOptionByName('Catalog *', 'Popcorn 2026', user);
    await user.click(await screen.findByTestId('form-dialog-confirm'));

    expect(await screen.findByText('That catalog is not yours to use.')).toBeInTheDocument();
    expect(screen.queryByTestId('created-campaign-note')).not.toBeInTheDocument();
  });

  it('the created campaign note holds the join code for copying and then dismisses', async () => {
    const created = campaignFixture();
    const mocks = [
      campaignsQuery([]),
      { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [catalogMock] } } },
      { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: [] } } },
      {
        request: {
          query: CREATE_UNIT_CAMPAIGN,
          variables: {
            input: {
              unitId: UNIT_ID,
              campaignName: 'Fall Popcorn',
              campaignYear: YEAR,
              catalogId: catalogMock.catalogId,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { createUnitCampaign: created } },
      },
      campaignsQuery([created]),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-campaign'));
    await typeInto('campaign-name', 'Fall Popcorn', user);
    await chooseOptionByName('Catalog *', 'Popcorn 2026', user);
    await user.click(await screen.findByTestId('form-dialog-confirm'));

    // The copy control sits next to the code it copies; jsdom's clipboard cannot be
    // observed from the component, so the note itself is what is checked.
    await user.click(await screen.findByTestId('copy-join-code'));
    expect(screen.getByTestId('created-join-code')).toHaveTextContent('JOIN1234CODE5678');

    await user.click(within(screen.getByTestId('created-campaign-note')).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByTestId('created-campaign-note')).not.toBeInTheDocument());
  });

  it('the roster link opens that campaign', async () => {
    renderPanel([campaignsQuery([campaignFixture()])]);

    await userEvent.setup().click(await screen.findByTestId(`roster-${CAMPAIGN_ID}`));
    expect(navigate).toHaveBeenCalledWith(`/show-sell/units/${UNIT_ID}/campaigns/${CAMPAIGN_ID}`);
  });


  it('states a campaign write refusal that carries no reason', async () => {
    const campaign = campaignFixture();
    renderPanel([
      campaignsQuery([campaign]),
      {
        request: {
          query: UPDATE_UNIT_CAMPAIGN,
          variables: {
            input: { unitCampaignId: CAMPAIGN_ID, isActive: false, version: { expectedVersion: 1 }, idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        error: new Error(''),
      },
      campaignsQuery([campaign]),
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId(`toggle-${CAMPAIGN_ID}`));
    await user.click(await screen.findByRole('button', { name: 'Close campaign' }));

    expect(await screen.findByText('Could not change this campaign.')).toBeInTheDocument();
  });


  it('a campaign the server refuses without a reason says so, and the note is not shown', async () => {
    renderPanel([
      campaignsQuery([]),
      { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [catalogMock] } } },
      { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: [] } } },
      {
        request: {
          query: CREATE_UNIT_CAMPAIGN,
          variables: {
            input: { unitId: UNIT_ID, campaignName: 'Fall Popcorn', campaignYear: YEAR, catalogId: catalogMock.catalogId, idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        error: new Error(''),
      },
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-campaign'));
    await typeInto('campaign-name', 'Fall Popcorn', user);
    await chooseOptionByName('Catalog *', 'Popcorn 2026', user);
    await user.click(await screen.findByTestId('form-dialog-confirm'));

    expect(await screen.findByText('Could not create the campaign.')).toBeInTheDocument();
  });

  it('a create that answers without a campaign body still refreshes and shows no note', async () => {
    renderPanel([
      campaignsQuery([]),
      { request: { query: LIST_MY_CATALOGS }, result: { data: { listMyCatalogs: [catalogMock] } } },
      { request: { query: LIST_MANAGED_CATALOGS }, result: { data: { listManagedCatalogs: [] } } },
      {
        request: {
          query: CREATE_UNIT_CAMPAIGN,
          variables: {
            input: { unitId: UNIT_ID, campaignName: 'Fall Popcorn', campaignYear: YEAR, catalogId: catalogMock.catalogId, idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: {} },
      },
      campaignsQuery([]),
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-campaign'));
    await typeInto('campaign-name', 'Fall Popcorn', user);
    await chooseOptionByName('Catalog *', 'Popcorn 2026', user);
    await user.click(await screen.findByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.queryByTestId('created-campaign-note')).not.toBeInTheDocument());
    expect(await screen.findByText(/No campaigns here yet/)).toBeInTheDocument();
  });


  it('shows the campaigns on later pages too, because choosing one needs the whole list', async () => {
    const second = campaignFixture({ unitCampaignId: 'UNITCAMP#pack-3149-winter', campaignName: 'Winter Popcorn', joinCode: 'JOIN1234CODE5679' });
    const mocks = [
      {
        request: { query: LIST_UNIT_CAMPAIGNS, variables: { unitId: UNIT_ID, isActive: undefined, page: { limit: UNIT_PAGE_SIZE } } },
        result: {
          data: {
            unitCampaigns: {
              __typename: 'UnitCampaignAdminConnection',
              items: [campaignFixture()],
              pageInfo: { __typename: 'PageInfo', endCursor: 'campaigns-cursor-2', hasNextPage: true },
            },
          },
        },
      },
      {
        request: { query: LIST_UNIT_CAMPAIGNS, variables: { unitId: UNIT_ID, isActive: undefined, page: { limit: UNIT_PAGE_SIZE, cursor: 'campaigns-cursor-2' } } },
        result: {
          data: {
            unitCampaigns: {
              __typename: 'UnitCampaignAdminConnection',
              items: [second],
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
      },
    ];
    renderPanel(mocks);

    expect(await screen.findByTestId(`campaign-row-${CAMPAIGN_ID}`)).toBeInTheDocument();
    expect(await screen.findByTestId('campaign-row-UNITCAMP#pack-3149-winter')).toBeInTheDocument();
  });
});
