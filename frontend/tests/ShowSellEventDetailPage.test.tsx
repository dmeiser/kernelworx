/**
 * One Show & Sell event, opened by its Unit Admin at the route that names it
 * (§3.5.1 detail: EVT-M-01 the identity, EVT-M-02 the settings edit with its
 * immutable interval, EVT-M-03 the cancellation record and the replacement event
 * of §6.1).
 *
 * The sibling suites already pin the list row and each board against its own
 * read, so this file pins only what exists at the seam between them:
 *
 * - **Every read is addressed by the route's own ids.** The page and the three
 *   boards underneath it all speak by id, so the variables that leave the
 *   browser are the proof that a stale bookmark, or a pasted id from another
 *   campaign, cannot render somebody else's boards. The ids the server mints
 *   for a Unit, a Unit Campaign and a Show & Sell are bare, so they are bare in
 *   the URL; `SLOT#`, `PROFILE#` and `PROD#` appear only inside payloads and in
 *   test ids.
 * - **The times on this screen are the Unit's wall clock.** The instant is
 *   absolute and only its reading moves: a Unit in America/Denver whose event
 *   starts at 15:00Z is on at 9:00 AM for the Kernel standing outside the store,
 *   whatever zone the browser happens to be set to.
 * - **The state decides which of the four actions exist** (SSE-06, SSE-07), and
 *   an action that is not on offer says why where its button would have been.
 * - **A refusal answers in a sentence.** FORBIDDEN, NOT_FOUND, an id that
 *   belongs to another campaign and a transport failure all get the same words:
 *   the screen never confirms that an id the caller may not reach is real. One
 *   render is mounted off the app's route on purpose — a path carrying none of
 *   the three ids — because it is the only way to see that the page reads by an
 *   empty id rather than an absent one.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { GraphQLError } from 'graphql';
import {
  CANCEL_SHOW_AND_SELL,
  GET_SHOW_AND_SELL,
  GET_UNIT,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_EVENT_INVENTORY_ALLOCATIONS,
  LIST_SHOW_AND_SELL_SALES,
  LIST_SHOW_AND_SELL_SIGNUPS,
  LIST_UNIT_CAMPAIGN_ROSTER,
  LIST_UNIT_PAYMENT_METHODS,
  LIST_WE_OWE_OBLIGATIONS,
} from '../src/lib/graphql';
import { ShowSellEventDetailPage } from '../src/pages/ShowSellEventDetailPage';
import { SHOW_AND_SELL_PAGE_SIZE } from '../src/lib/showSell';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { findOption, typeInto } from './helpers/unitUi';

const UNIT = 'pack-3149';
const UC = 'pack-3149-fall';
const SSE = 'library';
const ZONE = 'America/Denver';
const CARAMEL = 'PROD#caramel';
const BUTTER = 'PROD#butter';
const RETIRED = 'PROD#retired';
const FIRST = 'SLOT#first';
const AVERY = 'PROFILE#avery';

/** 15:00Z is 09:00 in the Unit's zone and 11:00 in the browser's. */
const START = '2026-03-28T15:00:00.000Z';
const END = '2026-03-28T18:30:00.000Z';

const DETAIL_PATH = '/show-sell/units/:unitId/campaigns/:unitCampaignId/show-sell/:showAndSellId';
const DETAIL_ROUTE = `/show-sell/units/${UNIT}/campaigns/${UC}/show-sell/${SSE}`;
const LIST_ROUTE = `/show-sell/units/${UNIT}/campaigns/${UC}/show-sell`;

/** The event read is re-issued after every header write, so one mock answers the lot. */
const READ_LIMIT = 8;

const EVENT_SENTENCE = 'This event is not yours, or it no longer exists.';

const ALLOCATION_VARIABLES = {
  unitCampaignId: UC,
  productId: undefined,
  showAndSellId: undefined,
  status: undefined,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
};
const SIGNUP_VARIABLES = { showAndSellId: SSE, status: undefined, page: { limit: SHOW_AND_SELL_PAGE_SIZE } };
const ROSTER_VARIABLES = { unitCampaignId: UC, status: undefined, page: { limit: UNIT_PAGE_SIZE } };

let keySequence = 0;
/** The variables each read actually carried out of the browser, in order. */
let sent: Record<string, unknown[]>;

beforeEach(() => {
  keySequence = 0;
  sent = { event: [], unit: [], catalog: [], allocations: [], signups: [], roster: [], sales: [], methods: [], obligations: [] };
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

const unitRow = {
  __typename: 'Unit',
  unitId: UNIT,
  unitType: 'Pack',
  unitNumber: '3149',
  city: 'Monroe',
  state: 'MI',
  displayName: 'Pack 3149',
  timezone: ZONE,
  splitDefault: 'EQUAL',
  councilNeedBasis: 'FLAT',
  adminCount: 2,
  version: 4,
  createdAt: '2026-01-01T15:00:00.000Z',
  updatedAt: '2026-02-01T15:00:00.000Z',
  createdByAccountId: 'ACCOUNT#casey',
};

/** One product's reservation for this event, as the allocation fragment answers it. */
function allocationFixture(productId: string, overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShowAndSellAllocation',
    unitCampaignId: UC,
    productId,
    showAndSellId: SSE,
    startAt: START,
    endAt: END,
    status: 'OPEN',
    allocatedQty: 24,
    soldQty: 0,
    releasedQty: 0,
    remainingQty: 24,
    version: 1,
    createdAt: '2026-03-10T15:00:00.000Z',
    updatedAt: '2026-03-10T15:00:00.000Z',
    ...overrides,
  };
}

function slotFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShowAndSellSlot',
    showAndSellId: SSE,
    slotId: FIRST,
    label: 'First Sales',
    startAt: START,
    endAt: '2026-03-28T16:30:00.000Z',
    capacity: 4,
    activeSignupCount: 1,
    version: 1,
    createdAt: '2026-03-10T15:00:00.000Z',
    updatedAt: '2026-03-10T15:00:00.000Z',
    ...overrides,
  };
}

function signupFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShowAndSellSignup',
    showAndSellId: SSE,
    slotId: FIRST,
    profileId: AVERY,
    unitCampaignId: UC,
    campaignId: 'CAMP#avery-fall',
    status: 'ACTIVE',
    actualMinutes: 0,
    signedUpByAccountId: 'ACCOUNT#avery',
    confirmedByAccountId: null,
    confirmedAt: null,
    version: 2,
    createdAt: '2026-03-25T15:00:00.000Z',
    updatedAt: '2026-03-25T15:00:00.000Z',
    ...overrides,
  };
}

function rosterFixture() {
  return {
    __typename: 'UnitCampaignMembership',
    unitCampaignId: UC,
    unitId: UNIT,
    campaignId: 'CAMP#avery-fall',
    profileId: AVERY,
    scoutName: 'Avery Scout',
    campaignName: 'Avery Fall Campaign',
    scoutCampaignCatalogId: 'CATALOG#popcorn-2026',
    status: 'ACTIVE',
    joinedByAccountId: 'ACCOUNT#avery',
    joinedAt: '2026-01-06T15:00:00.000Z',
    removedByAccountId: null,
    removedAt: null,
    version: 1,
    guardVersion: 1,
  };
}

/** The event as the admin fragment answers it: scheduled, at the library, on Main St. */
function eventFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: SSE,
    unitId: UNIT,
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: '200 Main St',
    startAt: START,
    endAt: END,
    status: 'SCHEDULED',
    splitMethod: 'TIME_WORKED',
    weOweEnabled: true,
    productIds: [CARAMEL, BUTTER, RETIRED],
    allocations: [allocationFixture(CARAMEL), allocationFixture(BUTTER)],
    slots: [slotFixture()],
    version: 7,
    createdAt: '2026-03-01T15:00:00.000Z',
    updatedAt: '2026-03-20T15:00:00.000Z',
    createdByAccountId: 'ACCOUNT#casey',
    updatedByAccountId: 'ACCOUNT#casey',
    cancelledByAccountId: null,
    cancelledAt: null,
    cancellationReason: null,
    ...overrides,
  } as never;
}

/**
 * Every read is built with a `result` function, so the variables that actually
 * reached the link are recorded. MockLink answers a mock only when the variables
 * match exactly, so a recorded value is the value the screen sent.
 */
function eventRead(event: unknown = eventFixture()) {
  return {
    request: { query: GET_SHOW_AND_SELL, variables: { showAndSellId: SSE } },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.event.push(variables);
      return { data: { showAndSell: event } };
    },
  };
}

function eventRefusal(error: Error) {
  return {
    request: { query: GET_SHOW_AND_SELL, variables: { showAndSellId: SSE } },
    maxUsageCount: READ_LIMIT,
    error,
  };
}

function unitRead() {
  return {
    request: { query: GET_UNIT, variables: { unitId: UNIT } },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.unit.push(variables);
      return { data: { unit: unitRow } };
    },
  };
}

function unitRefusal() {
  return {
    request: { query: GET_UNIT, variables: { unitId: UNIT } },
    maxUsageCount: READ_LIMIT,
    error: new GraphQLError('not yours', { extensions: { errorCode: 'FORBIDDEN' } }),
  };
}

function catalogRead() {
  return {
    request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: UC } },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.catalog.push(variables);
      return {
        data: {
          unitCampaignCatalog: {
            __typename: 'UnitCampaignCatalog',
            catalogId: 'CATALOG#popcorn-2026',
            catalogName: 'Popcorn 2026',
            products: [
              { __typename: 'CatalogProduct', productId: CARAMEL, productName: 'Caramel Corn', description: null, price: 6, sortOrder: 1 },
              { __typename: 'CatalogProduct', productId: BUTTER, productName: 'Butter Popcorn', description: null, price: 6, sortOrder: 2 },
            ],
          },
        },
      };
    },
  };
}

/** The campaign-wide allocation read: every event's rows, because the last column counts them all. */
function allocationsRead() {
  return {
    request: { query: LIST_EVENT_INVENTORY_ALLOCATIONS, variables: ALLOCATION_VARIABLES },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.allocations.push(variables);
      return {
        data: {
          eventInventoryAllocations: {
            __typename: 'EventInventoryAllocationConnection',
            items: [
              allocationFixture(CARAMEL),
              allocationFixture(CARAMEL, { showAndSellId: 'grove' }),
              allocationFixture(BUTTER, { status: 'RELEASED', releasedQty: 24, remainingQty: 0 }),
            ],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      };
    },
  };
}

function signupsRead() {
  return {
    request: { query: LIST_SHOW_AND_SELL_SIGNUPS, variables: SIGNUP_VARIABLES },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.signups.push(variables);
      return {
        data: {
          showAndSellSignups: {
            __typename: 'ShowAndSellSignupConnection',
            items: [signupFixture()],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      };
    },
  };
}

function rosterRead() {
  return {
    request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: ROSTER_VARIABLES },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.roster.push(variables);
      return {
        data: {
          unitCampaignRoster: {
            __typename: 'UnitCampaignMembershipConnection',
            items: [rosterFixture()],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      };
    },
  };
}

/** The reads the two money boards add to the page: the sales, the Unit's methods, the obligations. */
const DESK_SALES_VARIABLES = { showAndSellId: SSE, status: undefined, page: { limit: SHOW_AND_SELL_PAGE_SIZE } };
const METHODS_VARIABLES = { unitId: UNIT, includeInactive: true };
const OBLIGATIONS_VARIABLES = { unitCampaignId: UC, showAndSellId: SSE, status: undefined, page: { limit: SHOW_AND_SELL_PAGE_SIZE } };

function salesRead() {
  return {
    request: { query: LIST_SHOW_AND_SELL_SALES, variables: DESK_SALES_VARIABLES },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.sales.push(variables);
      return {
        data: {
          showAndSellSales: {
            __typename: 'ShowAndSellSaleConnection',
            items: [],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      };
    },
  };
}

function methodsRead() {
  return {
    request: { query: LIST_UNIT_PAYMENT_METHODS, variables: METHODS_VARIABLES },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.methods.push(variables);
      return {
        data: {
          unitPaymentMethods: [
            { __typename: 'UnitPaymentMethod', paymentMethodId: 'CASH', unitId: UNIT, displayName: 'Cash', isActive: true, qrCodeS3Key: null, createdAt: null, version: 0 },
            { __typename: 'UnitPaymentMethod', paymentMethodId: 'OTHER', unitId: UNIT, displayName: 'Other', isActive: true, qrCodeS3Key: null, createdAt: null, version: 0 },
          ],
        },
      };
    },
  };
}

function obligationsRead() {
  return {
    request: { query: LIST_WE_OWE_OBLIGATIONS, variables: OBLIGATIONS_VARIABLES },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.obligations.push(variables);
      return {
        data: {
          weOweObligations: {
            __typename: 'WeOweObligationConnection',
            items: [],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      };
    },
  };
}

/** The page opened on an event that is taking money, so the desk and the board can be mounted. */
function moneyPageReads() {
  return [...pageReads(eventFixture({ status: 'ACTIVE' })), salesRead(), methodsRead(), obligationsRead()];
}

/** The reads one mounted event page issues, so any tab can be opened in any test. */
function pageReads(event: unknown = eventFixture()) {
  return [eventRead(event), unitRead(), catalogRead(), allocationsRead(), signupsRead(), rosterRead()];
}

function cancelWrite(reason: string, idempotencyKey: string, released: unknown[], signups: unknown[]) {
  return {
    request: {
      query: CANCEL_SHOW_AND_SELL,
      variables: {
        input: {
          showAndSellId: SSE,
          reason,
          version: { expectedVersion: 7 },
          idempotency: { idempotencyKey },
        },
      },
    },
    result: {
      data: {
        cancelShowAndSell: {
          __typename: 'CancelShowAndSellResult',
          event: eventFixture({
            status: 'CANCELLED',
            cancellationReason: reason,
            cancelledByAccountId: 'ACCOUNT#casey',
            cancelledAt: '2026-03-21T15:00:00.000Z',
          }),
          releasedAllocations: released,
          cancelledSignups: signups,
        },
      },
    },
  };
}

/** The `showAndSellId` each recorded read was addressed by. */
function addressedBy(read: unknown[]): unknown[] {
  return read.map((variables) => (variables as { showAndSellId?: string }).showAndSellId);
}

/** The checkbox input inside a MUI Switch wrapper that carries the test id. */
function checkboxInside(switchElement: HTMLElement): HTMLInputElement {
  return switchElement.tagName === 'INPUT' ? (switchElement as HTMLInputElement) : (switchElement.querySelector('input') as HTMLInputElement);
}

/** Stands where the campaign's event list would be, so the back link can be followed. */
function LandedOnEvents() {
  const location = useLocation();
  return <div data-testid="landed-on-events">{location.pathname}</div>;
}

function renderPage(mocks: unknown[] = []) {
  render(
    <MockedProvider mocks={mocks as never}>
      <MemoryRouter initialEntries={[DETAIL_ROUTE]}>
        <Routes>
          <Route path={DETAIL_PATH} element={<ShowSellEventDetailPage />} />
          <Route path="/show-sell/units/:unitId/campaigns/:unitCampaignId/show-sell" element={<LandedOnEvents />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

/**
 * The page mounted on a path carrying none of the three ids — nowhere the app
 * routes to it, which is why this render exists at all. It is the only way to see
 * what the page does with a route that names nothing: it reads with empty ids,
 * never `undefined`, and answers the refusal sentence rather than rendering a
 * header around an event it never fetched.
 */
function renderPageWithoutIds(mocks: unknown[] = []) {
  render(
    <MockedProvider mocks={mocks as never}>
      <MemoryRouter initialEntries={['/show-sell/show-sell']}>
        <Routes>
          <Route path="/show-sell/show-sell" element={<ShowSellEventDetailPage />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

/** The two reads of a route with no ids: both addressed by an empty string. */
function emptyIdReads() {
  const eventReadMock = {
    request: { query: GET_SHOW_AND_SELL, variables: { showAndSellId: '' } },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.event.push(variables);
      return { data: { showAndSell: null } };
    },
  };
  const unitReadMock = {
    request: { query: GET_UNIT, variables: { unitId: '' } },
    maxUsageCount: READ_LIMIT,
    result: (variables: Record<string, unknown>) => {
      sent.unit.push(variables);
      return { data: { unit: null } };
    },
  };
  return [eventReadMock, unitReadMock];
}

describe('EVT-M-01: the header is the read, stated in the Unit’s own zone', () => {
  it('EVT-M-01: the event, the Unit and each board’s read are addressed by the route’s ids', async () => {
    renderPage(pageReads());

    expect(await screen.findByTestId('event-status')).toHaveTextContent('Scheduled');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Library on Main');
    // The page asks for one event, by the id in the route, and one Unit, by the id
    // in the route: nothing else leaves the browser for these two reads.
    expect(sent.event[0]).toEqual({ showAndSellId: SSE });
    expect(sent.unit[0]).toEqual({ unitId: UNIT });
    expect(addressedBy(sent.event)).toEqual([SSE]);
    // The stock board opens on the same mount and reads the campaign by the id in
    // the route — its own read, and the campaign-wide rows behind its last column.
    await screen.findByTestId('allocation-note');
    expect(sent.catalog[0]).toEqual({ unitCampaignId: UC });
    expect(sent.allocations[0]).toEqual(ALLOCATION_VARIABLES);
  });

  it('EVT-M-01: the interval is the Unit’s wall clock, not the browser’s', async () => {
    renderPage(pageReads());

    const interval = await screen.findByTestId('event-interval');
    // 15:00Z is 9:00 in America/Denver, the zone the Kernel and the Scouts stand
    // in; this machine's own zone would call the same instant 11:00.
    expect(interval.textContent).toContain('9:00 AM');
    expect(interval.textContent).toContain('12:30 PM');
    expect(interval.textContent).toContain('3 hours 30 minutes');
    // The browser's own zone appears nowhere on the page, not even as a quiet
    // second reading the admin could mistake for the event's.
    expect(screen.queryAllByText(/11:00/)).toHaveLength(0);
  });

  it('EVT-M-01: the state chip, the split and the We Owe state are the server’s answers', async () => {
    renderPage(pageReads(eventFixture({ splitMethod: 'TIME_WORKED', weOweEnabled: true })));

    expect(await screen.findByTestId('event-status')).toHaveTextContent('Scheduled');
    const settings = screen.getByTestId('event-settings');
    expect(settings.textContent).toContain('Split by worked time');
    expect(settings.textContent).toContain('We Owe on');
    // Every write from this page conditions on the version the page was read at.
    expect(screen.getByTestId('event-version').textContent).toContain('Event version 7');
    expect(screen.getByTestId('event-address').textContent).toContain('200 Main St');
  });

  it('EVT-M-01: an event with no address and We Owe off says both, and shows no empty address line', async () => {
    renderPage(pageReads(eventFixture({ address: null, weOweEnabled: false })));

    await screen.findByTestId('event-status');
    expect(screen.queryByTestId('event-address')).toBeNull();
    expect(screen.getByTestId('event-settings').textContent).toContain('We Owe off');
  });

  it('EVT-M-01: a Unit read that fails still names the event, with its times read in UTC', async () => {
    renderPage([eventRead(), unitRefusal(), catalogRead(), allocationsRead()]);

    const interval = await screen.findByTestId('event-interval');
    // The event's own times are absolute: with no zone to read them in, the screen
    // says so in UTC rather than inventing the browser's zone or going blank.
    expect(interval.textContent).toContain('3:00 PM');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Library on Main');
  });

  it('the back link returns to the campaign’s event list', async () => {
    const user = userEvent.setup();
    renderPage(pageReads());

    await screen.findByTestId('event-status');
    await user.click(screen.getByRole('button', { name: 'Back to events' }));

    expect((await screen.findByTestId('landed-on-events')).textContent).toBe(LIST_ROUTE);
  });

  it('the page waits on the event read rather than showing an empty page', async () => {
    renderPage(pageReads());

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByTestId('event-status')).toBeNull();
    await screen.findByTestId('event-status');
  });
});

describe('EVT-M-02, EVT-M-03: the four actions follow the event’s state', () => {
  it('EVT-M-02: a scheduled event offers Edit and Cancel, and no replacement', async () => {
    renderPage(pageReads());

    await screen.findByTestId('edit-event');
    expect(screen.getByTestId('edit-event')).toBeEnabled();
    expect(screen.getByTestId('cancel-event')).toBeEnabled();
    expect(screen.getByTestId('recreate-event')).toBeDisabled();
    expect(screen.queryByTestId('cancel-refusal-note')).toBeNull();
  });

  it('SSE-06: a running event offers no Cancel and says why where the button is', async () => {
    renderPage(pageReads(eventFixture({ status: 'ACTIVE' })));

    await screen.findByTestId('cancel-event');
    expect(screen.getByTestId('cancel-event')).toBeDisabled();
    expect(screen.getByTestId('recreate-event')).toBeDisabled();
    // Its settings stay editable while it runs (§3.1.3): the state closes
    // cancellation, not the record.
    expect(screen.getByTestId('edit-event')).toBeEnabled();
    expect(screen.getByTestId('cancel-refusal-note').textContent).toContain('already started');
    expect(screen.getByTestId('event-status')).toHaveTextContent('Running');
  });

  it('SSE-06: an ended event offers no Cancel, and finalizing is what closes it', async () => {
    renderPage(pageReads(eventFixture({ status: 'ENDED' })));

    await screen.findByTestId('cancel-event');
    expect(screen.getByTestId('cancel-event')).toBeDisabled();
    expect(screen.getByTestId('recreate-event')).toBeDisabled();
    expect(screen.getByTestId('cancel-refusal-note').textContent).toContain('finalizing');
    expect(screen.getByTestId('event-status')).toHaveTextContent('Ended, awaiting finalization');
  });

  it('EVT-M-03: a cancelled event keeps its reason in view and offers a replacement, not a cancel', async () => {
    renderPage(pageReads(eventFixture({
      status: 'CANCELLED',
      cancelledByAccountId: 'ACCOUNT#casey',
      cancelledAt: '2026-03-21T15:00:00.000Z',
      cancellationReason: 'Store closed for the holiday',
    })));

    expect(await screen.findByTestId('event-status')).toHaveTextContent('Cancelled');
    expect(screen.getByTestId('cancellation-reason').textContent).toContain('Cancelled: Store closed for the holiday');
    expect(screen.getByTestId('cancel-event')).toBeDisabled();
    expect(screen.getByTestId('edit-event')).toBeDisabled();
    expect(screen.getByTestId('recreate-event')).toBeEnabled();
    // A cancelled event is not a started one: the refusal note belongs to an event
    // that can still be finalized, and saying otherwise would send the admin to a
    // finalization that cannot happen.
    expect(screen.queryByTestId('cancel-refusal-note')).toBeNull();
  });

  it('EVT-M-03: a cancelled row with no stored reason shows no reason line', async () => {
    renderPage(pageReads(eventFixture({ status: 'CANCELLED', cancellationReason: null })));

    await screen.findByTestId('event-status');
    expect(screen.queryByTestId('cancellation-reason')).toBeNull();
  });

  it('EVT-M-03: the notice after a cancel counts what the write released', async () => {
    const user = userEvent.setup();
    renderPage([
      ...pageReads(),
      cancelWrite('Store closed for the holiday', 'test-idem-1', [allocationFixture(CARAMEL), allocationFixture(BUTTER)], [signupFixture()]),
      cancelWrite('Road work on Main St', 'test-idem-2', [allocationFixture(CARAMEL)], []),
    ]);

    await screen.findByTestId('cancel-event');
    await user.click(screen.getByTestId('cancel-event'));
    await typeInto('cancellation-reason-input', 'Store closed for the holiday', user);
    await user.click(screen.getByTestId('submit-cancel-event'));

    // The counts are the server's from the write's own answer, and the plurals
    // follow them: this is the sentence an admin reads to know what went back.
    expect((await screen.findByTestId('event-action-notice-text')).textContent).toBe(
      'Cancelled: 2 product allocations released back to the campaign, 1 Scout signup cancelled.',
    );
    await user.click(screen.getByTestId('dismiss-event-action-notice'));
    expect(screen.queryByTestId('event-action-notice')).toBeNull();

    await user.click(screen.getByTestId('cancel-event'));
    await typeInto('cancellation-reason-input', 'Road work on Main St', user);
    await user.click(screen.getByTestId('submit-cancel-event'));

    expect((await screen.findByTestId('event-action-notice-text')).textContent).toBe(
      'Cancelled: 1 product allocation released back to the campaign, 0 Scout signups cancelled.',
    );
  });
});

describe('SSE-07, §6.1: the dialogs the header opens', () => {
  it('EVT-M-02, SSE-07: Edit opens with the interval shown, locked, and named as unchangeable', async () => {
    const user = userEvent.setup();
    renderPage(pageReads());

    await screen.findByTestId('edit-event');
    await user.click(screen.getByTestId('edit-event'));

    expect(await screen.findByTestId('edit-event-title')).toHaveTextContent('Edit this Show & Sell');
    expect(screen.getByTestId('times-immutable-note').textContent).toContain('read-only');
    expect(screen.getByTestId('edit-event-times').textContent).toContain('9:00 AM');
    // The boxes carry the Unit's wall clock and cannot be typed in: the edit write
    // has no interval to carry, so offering them would offer a guaranteed refusal.
    expect(screen.getByTestId('event-start-input')).toHaveValue('2026-03-28T09:00');
    expect(screen.getByTestId('event-end-input')).toHaveValue('2026-03-28T12:30');
    expect(screen.getByTestId('event-start-input')).toBeDisabled();
    expect(screen.getByTestId('event-end-input')).toBeDisabled();
    expect(screen.getByTestId('event-location-input')).toHaveValue('Library on Main');
    // The form starts from the event's own split rather than the Unit's default,
    // so a save cannot silently move the split underneath the event.
    const eventSplit = await findOption('event-split-select', 'Split by worked time', user);
    expect(eventSplit.getAttribute('aria-selected')).toBe('true');
  });

  it('§6.1: Create another carries the cancelled event’s words and none of its times', async () => {
    const user = userEvent.setup();
    renderPage(pageReads(eventFixture({
      status: 'CANCELLED',
      cancelledByAccountId: 'ACCOUNT#casey',
      cancelledAt: '2026-03-21T15:00:00.000Z',
      cancellationReason: 'Store closed for the holiday',
    })));

    await screen.findByTestId('recreate-event');
    await user.click(screen.getByTestId('recreate-event'));

    expect(await screen.findByTestId('create-event-title')).toHaveTextContent('Create the replacement event');
    // §6.1: the replacement is a new row with its own id; nothing moves over.
    expect(screen.getByTestId('recreate-note').textContent).toContain('Library on Main');
    expect(screen.getByTestId('recreate-note').textContent).toContain('stays cancelled');
    expect(screen.getByTestId('event-location-input')).toHaveValue('Library on Main');
    expect(screen.getByTestId('event-address-input')).toHaveValue('200 Main St');
    // Only the words carry over. We Owe starts back at off and the split at *Inherit
    // the Unit default*: the replacement's money rules are a new decision, and
    // prefilling the cancelled event's would leave this event quietly running the rules
    // of one that was cancelled — with the admin's first save looking like it changed
    // nothing, because the form already held those values (§6.1).
    expect(checkboxInside(screen.getByTestId('event-we-owe-switch'))).not.toBeChecked();
    // A prefilled interval would invite a save that rebuilds the event at the very
    // moment it was cancelled for, so the times come back blank and editable.
    expect(screen.getByTestId('event-start-input')).toHaveValue('');
    expect(screen.getByTestId('event-end-input')).toHaveValue('');
    expect(screen.getByTestId('event-start-input')).toBeEnabled();
    expect(screen.queryByTestId('times-immutable-note')).toBeNull();
  });
});

describe('§3.5.2-§3.5.4: the boards under the header belong to this event', () => {
  it('each board is mounted for this event, and its read carries this event’s ids', async () => {
    const user = userEvent.setup();
    renderPage(pageReads());

    // Stock: the rows are this event's, including a product the catalog no longer
    // lists, because a row the editor cannot see is a reservation it cannot release.
    await screen.findByTestId(`allocation-row-${CARAMEL}`);
    expect(screen.getByTestId(`allocation-row-${RETIRED}`)).toBeInTheDocument();
    expect(sent.allocations[0]).toEqual(ALLOCATION_VARIABLES);

    // Slots: the board has no read of its own — it renders the slots of the event
    // read the header is standing on — so its own ids are the proof of which
    // event is mounted.
    await user.click(screen.getByTestId('tab-slots'));
    const slotRow = await screen.findByTestId(`slot-row-${FIRST}`);
    expect(within(slotRow).getByTestId(`slot-interval-${FIRST}`).textContent).toContain('9:00 AM');
    expect(screen.queryByTestId('no-slots')).toBeNull();

    // Signups and work: this board does read, and it reads by event id.
    await user.click(screen.getByTestId('tab-signups'));
    await screen.findByTestId(`signup-row-${FIRST}#${AVERY}`);
    expect(sent.signups[0]).toEqual(SIGNUP_VARIABLES);
    expect(sent.roster[0]).toEqual(ROSTER_VARIABLES);
    // Every signup read, first and any later one, is addressed by this event's id:
    // a stale route cannot leave another event's signups on this screen.
    expect(new Set(addressedBy(sent.signups))).toEqual(new Set([SSE]));
    expect(addressedBy(sent.event)).toEqual([SSE]);
  });

  it('the Sales desk and the We Owe board mount for this event, and read by its ids', async () => {
    const user = userEvent.setup();
    renderPage(moneyPageReads());

    // The page has to be standing on its event before a money board can be opened.
    await screen.findByTestId(`allocation-row-${CARAMEL}`);

    // Sales: the desk reads name this event — its own sales, the payment methods of
    // this Unit (retired ones included, because a sale entered with one is still
    // correctable), and the obligations its owing lines created.
    await user.click(screen.getByTestId('tab-sales'));
    await screen.findByTestId('sale-entry-form');
    expect(await screen.findByTestId('sale-list-empty')).toHaveTextContent('No sales');
    expect(sent.sales[0]).toEqual(DESK_SALES_VARIABLES);
    expect(sent.methods[0]).toEqual(METHODS_VARIABLES);
    expect(sent.obligations[0]).toEqual(OBLIGATIONS_VARIABLES);

    // We Owe: the board reads the same obligations, addressed by this event, and an
    // event with none says so rather than showing a blank table.
    await user.click(screen.getByTestId('tab-weowe'));
    await screen.findByTestId('we-owe-empty');
    expect(new Set(addressedBy(sent.obligations))).toEqual(new Set([SSE]));
    expect(
      new Set(sent.obligations.map((variables) => (variables as { unitCampaignId?: string }).unitCampaignId)),
    ).toEqual(new Set([UC]));
  });
});

describe('the read the page is standing on', () => {
  it('FORBIDDEN answers a sentence, not a blank page', async () => {
    renderPage([eventRefusal(new GraphQLError('not yours', { extensions: { errorCode: 'FORBIDDEN' } })), unitRead()]);

    await screen.findByText(EVENT_SENTENCE);
    expect(screen.queryByTestId('tab-allocations')).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('NOT_FOUND answers the same sentence, so an id is never confirmed real', async () => {
    renderPage([eventRefusal(new GraphQLError('no such event', { extensions: { errorCode: 'NOT_FOUND' } })), unitRead()]);

    await screen.findByText(EVENT_SENTENCE);
    expect(screen.queryByTestId('event-status')).toBeNull();
  });

  it('a transport failure answers the same sentence rather than a spinner forever', async () => {
    renderPage([eventRefusal(new Error('network is unreachable')), unitRead()]);

    await screen.findByText(EVENT_SENTENCE);
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('an event id under another campaign answers like one that does not exist', async () => {
    renderPage(pageReads(eventFixture({ unitCampaignId: 'pack-3149-winter' })));

    // The route says which campaign this event belongs to; an event that answers a
    // different one is not this caller's, and the screen does not explain which.
    await screen.findByText(EVENT_SENTENCE);
    expect(screen.queryByTestId('event-status')).toBeNull();
    expect(sent.event[0]).toEqual({ showAndSellId: SSE });
  });

  it('a route that names no id reads nothing and answers the same sentence', async () => {
    renderPageWithoutIds(emptyIdReads());

    // The ids the page reads by are always strings. An `undefined` id would be a
    // read the server can only refuse, and a header built out of nothing.
    await screen.findByText(EVENT_SENTENCE);
    await waitFor(() => expect(sent.unit).toHaveLength(1));
    expect(sent.event[0]).toEqual({ showAndSellId: '' });
    expect(sent.unit[0]).toEqual({ unitId: '' });
    expect(screen.queryByTestId('event-status')).toBeNull();
    expect(screen.queryByTestId('tab-allocations')).toBeNull();
  });
});
