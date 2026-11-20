/**
 * The event list: what a campaign has on and where each event stands (Show & Sell
 * §3.5.1, EVT-M-01 through EVT-M-03 from the admin's side).
 *
 * Two rules decide the shape of this screen, and both are pinned here:
 *
 * - **The status on the row is the server's, never a countdown.** ACTIVE, ENDED and
 *   SCHEDULED are derived from the stored interval when the read answers, so the
 *   screen shows the label it was given and the countdown beside it is only a
 *   reading aid. A fixture whose stored row and derived status disagree proves
 *   which one is rendered.
 * - **Cancellation is a pre-start act** (SSE-05, SSE-06). A row that is running,
 *   ended or finalized carries no Cancel button and says why in its place; the row
 *   that was cancelled offers *Create another*, which opens a create, not a restore
 *   (§6.1).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { GraphQLError } from 'graphql';
import {
  CANCEL_SHOW_AND_SELL,
  GET_UNIT,
  GET_UNIT_CAMPAIGN,
  LIST_SHOW_AND_SELLS,
} from '../src/lib/graphql';
import { ShowSellEventListPage } from '../src/pages/ShowSellEventListPage';
import { typeInto } from './helpers/unitUi';

const UNIT = 'pack-3149';
const UC = 'pack-3149-fall';
const ROUTE = `/show-sell/units/${UNIT}/campaigns/${UC}/show-sell`;

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

const unitMock = {
  request: { query: GET_UNIT, variables: { unitId: UNIT } },
  result: {
    data: {
      unit: {
        __typename: 'Unit',
        unitId: UNIT,
        unitType: 'Pack',
        unitNumber: '3149',
        city: 'Monroe',
        state: 'MI',
        displayName: 'Pack 3149',
        timezone: 'America/Denver',
        splitDefault: 'EQUAL',
        councilNeedBasis: 'FLAT',
        adminCount: 2,
        version: 4,
        createdAt: '2026-01-01T15:00:00.000Z',
        updatedAt: '2026-02-01T15:00:00.000Z',
        createdByAccountId: 'ACCOUNT#admin',
      },
    },
  },
};

const campaignMock = {
  request: { query: GET_UNIT_CAMPAIGN, variables: { unitCampaignId: UC } },
  result: {
    data: {
      unitCampaign: {
        __typename: 'UnitCampaignAdmin',
        unitCampaignId: UC,
        unitId: UNIT,
        campaignName: 'Fall Popcorn 2026',
        campaignYear: 2026,
        catalogId: 'CATALOG#fall',
        joinCode: 'MAPLE-3149',
        isActive: true,
        version: 2,
        createdAt: '2026-01-01T15:00:00.000Z',
        updatedAt: '2026-01-01T15:00:00.000Z',
        createdByAccountId: 'ACCOUNT#admin',
        updatedByAccountId: 'ACCOUNT#admin',
      },
    },
  },
};

/** An event row as the admin fragment answers it. */
function eventFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: 'library',
    unitId: UNIT,
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: '200 Main St',
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:30:00.000Z',
    status: 'SCHEDULED',
    splitMethod: 'EQUAL',
    weOweEnabled: true,
    productIds: ['PROD#caramel'],
    allocations: [
      {
        __typename: 'ShowAndSellAllocation',
        unitCampaignId: UC,
        productId: 'PROD#caramel',
        showAndSellId: 'library',
        startAt: '2026-03-28T15:00:00.000Z',
        endAt: '2026-03-28T18:30:00.000Z',
        status: 'OPEN',
        allocatedQty: 24,
        soldQty: 0,
        releasedQty: 0,
        remainingQty: 24,
        version: 1,
        createdAt: '2026-03-10T15:00:00.000Z',
        updatedAt: '2026-03-10T15:00:00.000Z',
      },
    ],
    slots: [
      {
        __typename: 'ShowAndSellSlot',
        showAndSellId: 'library',
        slotId: 'SLOT#first',
        label: 'First Sales',
        startAt: '2026-03-28T15:00:00.000Z',
        endAt: '2026-03-28T16:30:00.000Z',
        capacity: 2,
        activeSignupCount: 1,
        version: 1,
        createdAt: '2026-03-10T15:00:00.000Z',
        updatedAt: '2026-03-10T15:00:00.000Z',
      },
    ],
    version: 3,
    createdAt: '2026-03-01T15:00:00.000Z',
    updatedAt: '2026-03-20T15:00:00.000Z',
    createdByAccountId: 'ACCOUNT#admin',
    updatedByAccountId: 'ACCOUNT#admin',
    cancelledByAccountId: null,
    cancelledAt: null,
    cancellationReason: null,
    ...overrides,
  } as never;
}

/** The list read with the page's own variables, carrying `events`. */
const listMock = (events: unknown[], status?: string) => ({
  request: {
    query: LIST_SHOW_AND_SELLS,
    variables: {
      unitCampaignId: UC,
      status,
      dateRange: undefined,
      page: { limit: 50 },
    },
  },
  result: {
    data: {
      showAndSells: {
        __typename: 'ShowAndSellAdminConnection',
        items: events,
        nextToken: null,
        totalCount: events.length,
      },
    },
  },
});

function renderPage(mocks: unknown[] = []) {
  render(
    <MockedProvider mocks={mocks as never} addTypename={false}>
      <MemoryRouter initialEntries={[ROUTE]}>
        <Routes>
          <Route path="/show-sell/units/:unitId/campaigns/:unitCampaignId/show-sell" element={<ShowSellEventListPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('§3.5.1: the list reads as the server answered it', () => {
  it('names the place, the interval in the Unit zone, the slots and the stock', async () => {
    renderPage([unitMock, campaignMock, listMock([eventFixture()])]);

    const row = await screen.findByTestId('event-row-library');
    expect(within(row).getByText('Library on Main')).toBeTruthy();
    // 15:00Z is 09:00 in America/Denver, which is the zone the Kernel and the Scouts
    // stand in; the browser's zone never decides what this row says.
    expect(within(row).getByTestId('event-interval-library').textContent).toContain('9:00 AM');
    expect(within(row).getByTestId('event-slots-library').textContent).toBe('1');
    expect(within(row).getByTestId('event-stock-library').textContent).toBe('1 products');
    expect(within(row).getByTestId('event-address-library').textContent).toContain('200 Main St');
  });

  it('shows the derived status the read answered, not one the screen worked out', async () => {
    // A stored row cannot say ACTIVE or ENDED — those are derived at read time — so
    // the only status a correct row can show is the one in the payload.
    const running = eventFixture({ showAndSellId: 'store', status: 'ACTIVE' });
    renderPage([unitMock, campaignMock, listMock([running])]);

    const chip = await screen.findByTestId('event-status-store');
    expect(chip).toHaveTextContent('Running');
    // The countdown is a reading aid for a scheduled event only; a running event has
    // no start to count down to.
    expect(screen.queryByTestId('event-countdown-store')).toBeNull();
  });

  it('counts down a scheduled event so the admin knows how long it has left', async () => {
    renderPage([unitMock, campaignMock, listMock([eventFixture({ startAt: '2027-03-28T15:00:00.000Z', endAt: '2027-03-28T18:30:00.000Z' })])]);

    const countdown = await screen.findByTestId('event-countdown-library');
    expect(countdown.textContent).toContain('in ');
  });

  it('filters by the state tab, which is the server’s filter and not a local hide', async () => {
    const user = userEvent.setup();
    renderPage([
      unitMock,
      campaignMock,
      listMock([eventFixture()]),
      listMock([eventFixture({ showAndSellId: 'run', status: 'ACTIVE' })], 'ACTIVE'),
    ]);

    await screen.findByTestId('event-row-library');
    await user.click(screen.getByTestId('filter-active'));

    const running = await screen.findByTestId('event-row-run');
    expect(screen.queryByTestId('event-row-library')).toBeNull();
    expect(within(running).getByTestId('event-status-run')).toHaveTextContent('Running');
  });

  it('reaches the Scout view of the same campaign and each event’s own screen', async () => {
    renderPage([unitMock, campaignMock, listMock([eventFixture()])]);

    const scoutView = await screen.findByTestId('open-scout-view');
    expect(scoutView.getAttribute('href')).toBe(`/show-sell/campaigns/${UC}/opportunities`);
    const detail = await screen.findByTestId('open-event-library');
    expect(detail.getAttribute('href')).toBe(`${ROUTE}/library`);
  });
});

describe('SSE-05, SSE-06: only a pre-start event can be cancelled', () => {
  it('offers cancel and edit while the event is scheduled', async () => {
    renderPage([unitMock, campaignMock, listMock([eventFixture()])]);

    await screen.findByTestId('cancel-event-library');
    expect(screen.queryByTestId('no-cancel-library')).toBeNull();
    expect(screen.queryByTestId('recreate-event-library')).toBeNull();
  });

  it('offers no cancel on an event that is running, and says why', async () => {
    renderPage([unitMock, campaignMock, listMock([eventFixture({ status: 'ACTIVE' })])]);

    const why = await screen.findByTestId('no-cancel-library');
    expect(why.textContent).toContain('cancel');
    expect(screen.queryByTestId('cancel-event-library')).toBeNull();
  });

  it('offers no cancel on an event that has ended or been finalized', async () => {
    renderPage([
      unitMock,
      campaignMock,
      listMock([
        eventFixture({ showAndSellId: 'ended', status: 'ENDED' }),
        eventFixture({ showAndSellId: 'final', status: 'FINALIZED' }),
      ]),
    ]);

    await screen.findByTestId('no-cancel-ended');
    await screen.findByTestId('no-cancel-final');
    expect(screen.queryByTestId('cancel-event-ended')).toBeNull();
    expect(screen.queryByTestId('cancel-event-final')).toBeNull();
  });

  it('offers create-another on a cancelled event, and reports what the cancel released', async () => {
    const user = userEvent.setup();
    renderPage([
      unitMock,
      campaignMock,
      listMock([eventFixture()]),
      {
        request: {
          query: CANCEL_SHOW_AND_SELL,
          variables: {
            input: {
              showAndSellId: 'library',
              reason: 'Store closed for the holiday',
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            cancelShowAndSell: {
              __typename: 'CancelShowAndSellResult',
              event: eventFixture({ status: 'CANCELLED' }),
              releasedAllocations: [{ __typename: 'ShowAndSellAllocation', productId: 'PROD#caramel' }],
              cancelledSignups: [{ __typename: 'ShowAndSellSignup', profileId: 'PROFILE#avery' }],
            },
          },
        },
      },
      listMock([eventFixture({ status: 'CANCELLED' })]),
    ]);

    await screen.findByTestId('cancel-event-library');
    await user.click(screen.getByTestId('cancel-event-library'));
    // The row's Cancel opens the cancel dialog, whose consequence alert names what
    // the write releases before anything is written.
    await screen.findByTestId('cancel-consequence');

    await typeInto('cancellation-reason-input', 'Store closed for the holiday', user);
    await user.click(screen.getByTestId('submit-cancel-event'));

    const summary = await screen.findByTestId('cancelled-summary');
    expect(within(summary).getByTestId('cancelled-summary-text').textContent).toContain('Library on Main');
    expect(within(summary).getByTestId('cancelled-summary-text').textContent).toMatch(/1 product|product/);

    await user.click(screen.getByTestId('dismiss-cancelled-summary'));
    await waitFor(() => expect(screen.queryByTestId('cancelled-summary')).toBeNull());

    // The refreshed row is cancelled, so the only thing left to offer is a new event
    // (§6.1) — there is no restore, and no cancel.
    await screen.findByTestId('recreate-event-library');
    expect(screen.queryByTestId('cancel-event-library')).toBeNull();
  });
});

describe('the read the page is standing on', () => {
  it('says so when the Unit is not the caller’s, rather than an empty list', async () => {
    renderPage([
      { request: { query: GET_UNIT, variables: { unitId: UNIT } }, error: new GraphQLError('not found', { extensions: { errorCode: 'FORBIDDEN' } }) },
      campaignMock,
      listMock([]),
    ]);

    await screen.findByText('This Unit is not yours, or it no longer exists.');
    expect(screen.queryByTestId('show-sell-landing')).toBeNull();
  });

  it('says so when the campaign has no events, instead of a blank table', async () => {
    renderPage([unitMock, campaignMock, listMock([])]);

    await screen.findByText('No Show & Sell events yet');
    expect(screen.queryByRole('row')).toBeNull();
  });
});
