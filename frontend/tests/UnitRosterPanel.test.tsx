/**
 * Unit Campaign roster (§1.6.3) — Blake-history-preservation.
 *
 * Removing a Scout changes eligibility and nothing else: the row stays, carrying who
 * removed them and when, because their orders, credit, work minutes, and held stock
 * are this campaign's history. The write carries two versions because two rows move
 * (the roster row and the Scout Campaign's join guard), and the roster query is what
 * answers both.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { UnitRosterPanel } from '../src/components/UnitRosterPanel';
import { LIST_UNIT_CAMPAIGN_ROSTER, REMOVE_UNIT_CAMPAIGN_MEMBERSHIP } from '../src/lib/graphql';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { membershipFixture } from './helpers/unitFixtures';
import { chooseOption } from './helpers/unitUi';

const CAMPAIGN_ID = 'UNITCAMP#pack-3149-fall';
const PAGE = { unitCampaignId: CAMPAIGN_ID, status: undefined, page: { limit: UNIT_PAGE_SIZE } };

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

const devon = membershipFixture();
const blake = membershipFixture({
  profileId: 'PROFILE#blake',
  campaignId: 'CAMPAIGN#blake',
  status: 'REMOVED',
  joinedByAccountId: 'ACCOUNT#avery',
  removedByAccountId: 'ACCOUNT#avery',
  removedAt: '2026-02-11T15:00:00Z',
  version: 2,
  guardVersion: null,
});

function rosterQuery(items: unknown[]) {
  return {
    request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: PAGE },
    result: {
      data: {
        unitCampaignRoster: {
          __typename: 'UnitCampaignMembershipConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function renderPanel(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      <UnitRosterPanel unitCampaignId={CAMPAIGN_ID} />
    </MockedProvider>,
  );
}

describe('UnitRosterPanel', () => {
  it('keeps a removed Scout on the roster with who removed them and when', async () => {
    renderPanel([rosterQuery([devon, blake])]);

    const devonRow = await screen.findByTestId('roster-row-PROFILE#devon');
    const blakeRow = screen.getByTestId('roster-row-PROFILE#blake');
    expect(within(devonRow).getByTestId('roster-status-PROFILE#devon')).toHaveTextContent('Joined');
    expect(within(blakeRow).getByTestId('roster-status-PROFILE#blake')).toHaveTextContent('Removed');
    expect(within(blakeRow).getByTestId('roster-removed-PROFILE#blake')).toHaveTextContent('ACCOUNT#avery');
    expect(screen.getByTestId('roster-count')).toHaveTextContent('2 roster entries');

    // A removed row has nothing left to remove.
    expect(within(blakeRow).getByTestId('no-action-PROFILE#blake')).toBeInTheDocument();
  });

  it('removal carries both versions it moves, and the row survives as history', async () => {
    const removed = {
      ...devon,
      status: 'REMOVED',
      removedByAccountId: 'ACCOUNT#avery',
      removedAt: '2026-02-12T15:00:00Z',
      version: 2,
      guardVersion: null,
    };
    const mocks = [
      rosterQuery([devon, blake]),
      {
        request: {
          query: REMOVE_UNIT_CAMPAIGN_MEMBERSHIP,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              campaignId: 'CAMPAIGN#devon',
              expectedMembershipVersion: 1,
              expectedGuardVersion: 1,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { removeUnitCampaignMembership: removed } },
      },
      rosterQuery([removed, blake]),
    ];
    renderPanel(mocks);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('remove-member-PROFILE#devon'));
    await user.click(await screen.findByRole('button', { name: 'Remove from campaign' }));

    await waitFor(() => expect(screen.getByTestId('roster-status-PROFILE#devon')).toHaveTextContent('Removed'));
    expect(screen.getByTestId('roster-removed-PROFILE#devon')).toHaveTextContent('ACCOUNT#avery');
    expect(screen.queryAllByRole('alert')).toHaveLength(0);
    expect(screen.getByTestId('roster-count')).toHaveTextContent('2 roster entries');
  });


  it('re-reads the roster with the status the filter names', async () => {
    const mocks = [
      rosterQuery([devon, blake]),
      {
        request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { ...PAGE, status: 'REMOVED' } },
        result: {
          data: {
            unitCampaignRoster: {
              __typename: 'UnitCampaignMembershipConnection',
              items: [blake],
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
      },
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await chooseOption('roster-filter', 'Removed only', user);

    expect(await screen.findByTestId('roster-count')).toHaveTextContent('1 roster entry');
  });

  it('says when nothing matches the filter, and when the read failed', async () => {
    renderPanel([
      rosterQuery([]),
      {
        request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { ...PAGE, status: 'ACTIVE' } },
        result: {
          data: {
            unitCampaignRoster: {
              __typename: 'UnitCampaignMembershipConnection',
              items: [],
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
      },
    ]);
    const user = userEvent.setup();

    expect(await screen.findByText('No roster entries match this filter.')).toBeInTheDocument();
    await chooseOption('roster-filter', 'Active only', user);
    await waitFor(() => expect(screen.getAllByText('No roster entries match this filter.').length).toBeGreaterThan(0));
  });

  it('a refused removal leaves the roster standing and says why', async () => {
    const mocks = [
      rosterQuery([devon, blake]),
      {
        request: {
          query: REMOVE_UNIT_CAMPAIGN_MEMBERSHIP,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              campaignId: 'CAMPAIGN#devon',
              expectedMembershipVersion: 1,
              expectedGuardVersion: 1,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('That Scout has stock held against this campaign.', { extensions: { code: 'CONFLICT' } }),
      },
      rosterQuery([devon, blake]),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('remove-member-PROFILE#devon'));
    await user.click(await screen.findByRole('button', { name: 'Remove from campaign' }));

    expect(await screen.findByText('That Scout has stock held against this campaign.')).toBeInTheDocument();
    expect(await screen.findByTestId('roster-status-PROFILE#devon')).toHaveTextContent('Joined');
  });

  it('a roster that failed to read is not shown as an empty one', async () => {
    renderPanel([
      { request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: PAGE }, error: new GraphQLError('offline') },
    ]);

    expect(await screen.findByText("Could not load this campaign's roster.")).toBeInTheDocument();
  });


  it('shows what it has for a history row, even when the audit is thin', async () => {
    const noGuardRow = membershipFixture({ profileId: 'PROFILE#no-guard', campaignId: 'CAMPAIGN#no-guard', guardVersion: null });
    const thin = membershipFixture({
      profileId: 'PROFILE#thin',
      campaignId: 'CAMPAIGN#thin',
      status: 'REMOVED',
      joinedAt: 'not a date',
      removedByAccountId: null,
      removedAt: 'also not a date',
    });
    renderPanel([rosterQuery([noGuardRow, thin])]);

    // An ACTIVE row whose guard row cannot be answered gets no button: the write
    // would have nothing to condition on.
    expect(await screen.findByTestId('no-action-PROFILE#no-guard')).toHaveTextContent('Unavailable');
    expect(screen.getByTestId('roster-removed-PROFILE#thin')).toHaveTextContent('also not a date · unknown');
    expect(screen.getByTestId('roster-row-PROFILE#thin')).toHaveTextContent('not a date');
  });

  it('says the server reason when a removal fails with none', async () => {
    const mocks = [
      rosterQuery([devon, blake]),
      {
        request: {
          query: REMOVE_UNIT_CAMPAIGN_MEMBERSHIP,
          variables: {
            input: {
              unitCampaignId: CAMPAIGN_ID,
              campaignId: 'CAMPAIGN#devon',
              expectedMembershipVersion: 1,
              expectedGuardVersion: 1,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new Error(''),
      },
      rosterQuery([devon, blake]),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('remove-member-PROFILE#devon'));
    await user.click(await screen.findByRole('button', { name: 'Remove from campaign' }));

    expect(await screen.findByText('That Scout could not be removed.')).toBeInTheDocument();
  });


  it('walks the roster cursor, so the list is the whole roster and not page one', async () => {
    const firstPage = {
      request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: PAGE },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [devon],
            pageInfo: { __typename: 'PageInfo', endCursor: 'roster-cursor-2', hasNextPage: true },
          },
        },
      },
    };
    const secondPage = {
      request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { ...PAGE, page: { limit: UNIT_PAGE_SIZE, cursor: 'roster-cursor-2' } } },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [blake],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      },
    };
    renderPanel([firstPage, secondPage]);

    expect(await screen.findByTestId('roster-row-PROFILE#devon')).toBeInTheDocument();
    expect(await screen.findByTestId('roster-row-PROFILE#blake')).toBeInTheDocument();
    expect(screen.getByTestId('roster-count')).toHaveTextContent('2 roster entries');
  });

  it('says it is still fetching when a page two is on its way', async () => {
    const firstPage = {
      request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: PAGE },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [devon],
            pageInfo: { __typename: 'PageInfo', endCursor: 'roster-cursor-2', hasNextPage: true },
          },
        },
      },
    };
    const secondPage = {
      request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { ...PAGE, page: { limit: UNIT_PAGE_SIZE, cursor: 'roster-cursor-2' } } },
      delay: 150,
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [blake],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      },
    };
    renderPanel([firstPage, secondPage]);

    // The count a partial list shows is a claim about the roster, so the screen says
    // while the claim is provisional rather than letting a short list read as final.
    expect(await screen.findByTestId('roster-row-PROFILE#devon')).toBeInTheDocument();
    expect(await screen.findByTestId('connection-rest-loading')).toBeInTheDocument();

    await waitFor(() => expect(screen.queryByTestId('connection-rest-loading')).not.toBeInTheDocument());
    expect(await screen.findByTestId('roster-row-PROFILE#blake')).toBeInTheDocument();
  });

  it('says when the rest of the roster could not be fetched', async () => {
    const firstPage = {
      request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: PAGE },
      result: {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [devon],
            pageInfo: { __typename: 'PageInfo', endCursor: 'roster-cursor-2', hasNextPage: true },
          },
        },
      },
    };
    const failedPage = {
      request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { ...PAGE, page: { limit: UNIT_PAGE_SIZE, cursor: 'roster-cursor-2' } } },
      error: new GraphQLError('offline'),
    };
    renderPanel([firstPage, failedPage]);

    expect(await screen.findByTestId('roster-row-PROFILE#devon')).toBeInTheDocument();
    expect(await screen.findByText('The rest of this list could not be loaded, so some rows are not shown.')).toBeInTheDocument();
  });
});
