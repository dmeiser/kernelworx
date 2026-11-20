/**
 * The allocation editor: how many Kernels one event holds, per product
 * (§3.5.2, built on §3.2.1-§3.2.4; SS-SM-05's four-box workflow).
 *
 * What each assertion pins, and why it matters:
 *
 * - Each row shows four numbers with three different owners: what this event
 *   holds, what it sold, what it still has unsold (all the server's stored
 *   answers), and what every OPEN allocation of the campaign holds across all
 *   events — the last one is §3.2.4's browser sum, and it is only honest when
 *   every page has been fetched, which the 16-product case proves.
 * - The field is a TARGET, never a delta. A product the admin never typed, or
 *   typed exactly as it already holds, is left out of the batch entirely — a
 *   write that "assigns" an unchanged number is an audit row nobody asked for.
 *   A cleared target of zero IS sent, because zero is how the remainder goes
 *   back on the shelf (ALLOC-01).
 * - Over-assignment across events that never overlap succeeds with the
 *   server's warning sentence rendered as written — never clamped down to
 *   stock, because a campaign may legitimately hold a morning and an afternoon
 *   event against the same four Kernels (ALLOC-03, ALLOC-04).
 * - A plan that is not a whole number is refused before any write exists, and
 *   the save button itself is dead while there is nothing to save (ALLOC-08).
 * - A finalized or cancelled event cannot change its allocations; a reopened
 *   one saves only a draft whose balances belong to re-finalization.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { AllocationEditor } from '../src/components/showSell/AllocationEditor';
import {
  ASSIGN_SHOW_AND_SELL_INVENTORY,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_EVENT_INVENTORY_ALLOCATIONS,
} from '../src/lib/graphql';
import { SHOW_AND_SELL_PAGE_SIZE } from '../src/lib/showSell';
import { clearAndType } from './helpers/unitUi';
import type {
  GqlShowAndSellAdminFieldsFragment,
  GqlShowAndSellAllocationFieldsFragment,
} from '../src/types/graphql-generated';

const UC = 'UNITCAMP#pack-3149-fall';
const SSE = 'SSE#library';
const CARAMEL = 'PROD#caramel';
const BUTTER = 'PROD#butter';
const RETIRED = 'PROD#retired';

const STALE_SENTENCE =
  'That was refused because the event, a slot, or a signup has already moved. Reload this screen and try again with what it now shows.';

// The campaign's allocation read asks for exactly these variables; a paged
// continuation repeats them with the cursor added.
const ALLOC_VARIABLES = {
  unitCampaignId: UC,
  productId: undefined,
  showAndSellId: undefined,
  status: undefined,
  page: { limit: SHOW_AND_SELL_PAGE_SIZE },
};

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function productFixture(index: number) {
  const productId = index === 1 ? CARAMEL : `PROD#p${index}`;
  return {
    __typename: 'CatalogProduct',
    productId,
    productName: index === 1 ? 'Caramel Corn' : `Kernel ${index}`,
    description: null,
    price: 6,
    sortOrder: index,
  };
}

function catalogQuery(products: unknown[] = [{ __typename: 'CatalogProduct', productId: CARAMEL, productName: 'Caramel Corn', description: null, price: 6, sortOrder: 1 }, { __typename: 'CatalogProduct', productId: BUTTER, productName: 'Butter Popcorn', description: null, price: 6, sortOrder: 2 }]) {
  return {
    request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: UC } },
    result: {
      data: {
        unitCampaignCatalog: { __typename: 'UnitCampaignCatalog', catalogId: 'CATALOG#popcorn-2026', catalogName: 'Popcorn 2026', products },
      },
    },
  };
}

function allocFixture(
  productId: string,
  showAndSellId: string,
  allocatedQty: number,
  overrides: Partial<GqlShowAndSellAllocationFieldsFragment> = {},
): GqlShowAndSellAllocationFieldsFragment {
  return {
    __typename: 'ShowAndSellAllocation',
    unitCampaignId: UC,
    productId,
    showAndSellId,
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:30:00.000Z',
    status: 'OPEN',
    allocatedQty,
    soldQty: 0,
    releasedQty: 0,
    remainingQty: allocatedQty,
    version: 2,
    createdAt: '2026-03-21T15:00:00.000Z',
    updatedAt: '2026-03-21T15:00:00.000Z',
    ...overrides,
  };
}

function allocationsQuery(items: unknown[], endCursor: string | null = null, hasNextPage = false) {
  return {
    request: { query: LIST_EVENT_INVENTORY_ALLOCATIONS, variables: ALLOC_VARIABLES },
    result: {
      data: {
        eventInventoryAllocations: {
          __typename: 'EventInventoryAllocationConnection',
          items,
          pageInfo: { __typename: 'PageInfo', endCursor, hasNextPage },
        },
      },
    },
  };
}

/** The campaign-wide rows behind the first page's numbers. */
const CAMPAIGN_ROWS = [
  allocFixture(CARAMEL, SSE, 4, { soldQty: 1, remainingQty: 3 }),
  allocFixture(CARAMEL, 'SSE#grove', 2),
  allocFixture(BUTTER, 'SSE#grove', 5),
  // A released row reserves nothing, so it never counts toward "assigned
  // across all events" even though the allocation exists.
  allocFixture(CARAMEL, 'SSE#old', 7, { status: 'RELEASED', releasedQty: 7, remainingQty: 0 }),
];

function eventFixture(overrides: Partial<GqlShowAndSellAdminFieldsFragment> = {}): GqlShowAndSellAdminFieldsFragment {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: SSE,
    unitId: 'UNIT#pack-3149',
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: null,
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:30:00.000Z',
    status: 'SCHEDULED',
    splitMethod: 'TIME_WORKED',
    weOweEnabled: false,
    productIds: [CARAMEL, RETIRED],
    allocations: [
      allocFixture(CARAMEL, SSE, 4, { soldQty: 1, remainingQty: 3 }),
      allocFixture(BUTTER, SSE, 2, { status: 'RELEASED', soldQty: 2, remainingQty: 0 }),
    ],
    slots: [],
    version: 7,
    createdAt: '2026-03-21T15:00:00.000Z',
    updatedAt: '2026-03-21T15:00:00.000Z',
    createdByAccountId: 'ACCOUNT#casey',
    updatedByAccountId: 'ACCOUNT#casey',
    cancelledByAccountId: null,
    cancelledAt: null,
    cancellationReason: null,
    ...overrides,
  };
}

function renderEditor(mocks: unknown[], event = eventFixture()) {
  const onChanged = vi.fn(async () => undefined);
  render(
    <MockedProvider mocks={mocks as never}>
      <AllocationEditor event={event} onChanged={onChanged} />
    </MockedProvider>,
  );
  return onChanged;
}

function assignMock(items: unknown[], warnings?: unknown[]) {
  return {
    request: {
      query: ASSIGN_SHOW_AND_SELL_INVENTORY,
      variables: { input: { showAndSellId: SSE, items, version: { expectedVersion: 7 }, idempotency: { idempotencyKey: 'test-idem-1' } } },
    },
    result: {
      data: {
        assignShowAndSellInventory: {
          __typename: 'AssignShowAndSellInventoryPayload',
          allocations: items.map((item) => {
            const row = item as { productId: string; quantity: number };
            return allocFixture(row.productId, SSE, row.quantity);
          }),
          inventoryPositions: [],
          ...(warnings === undefined ? {} : { warnings }),
        },
      },
    },
  };
}

describe('AllocationEditor', () => {
  it('ALLOC-01: each row carries the four numbers — what this event holds, sold, still unsold, and assigned across the campaign', async () => {
    renderEditor([catalogQuery(), allocationsQuery(CAMPAIGN_ROWS)]);

    // Caramel: the event holds four, sold one, has three unsold, and the
    // campaign's OPEN allocations total six across every event. The RELEASED
    // seven is not counted: it reserves nothing any more.
    const target = await screen.findByTestId(`allocation-target-${CARAMEL}`);
    expect(target).toHaveValue('4');
    expect(screen.getByTestId(`allocation-sold-${CARAMEL}`)).toHaveTextContent('1');
    expect(screen.getByTestId(`allocation-remaining-${CARAMEL}`)).toHaveTextContent('3');
    expect(screen.getByTestId(`allocation-assigned-${CARAMEL}`)).toHaveTextContent('6');

    // Butter: its only allocation for this event was released, so the target
    // box starts blank and the sold/unsold numbers are the server's zeroes.
    expect(screen.getByTestId(`allocation-target-${BUTTER}`)).toHaveValue('');
    expect(screen.getByTestId(`allocation-sold-${BUTTER}`)).toHaveTextContent('0');
    expect(screen.getByTestId(`allocation-remaining-${BUTTER}`)).toHaveTextContent('0');
    expect(screen.getByTestId(`allocation-assigned-${BUTTER}`)).toHaveTextContent('5');

    // A product the catalog no longer lists still gets a row: an allocation
    // the editor cannot see is a reservation the admin cannot release. It is
    // named by its id because that is all there is to name it by.
    expect(screen.getByTestId(`allocation-name-${RETIRED}`)).toHaveTextContent(RETIRED);

    // The write is versioned against the event, and it reserves — it does not
    // move physical stock; the screen says so where the save button is.
    expect(screen.getByTestId('allocation-event-version')).toHaveTextContent(
      'Saved against event version 7. Physical stock does not move: this reserves stock for the event.',
    );
  });

  it('ALLOC-01: a target of zero for a product the event holds is sent as a zero row', async () => {
    const user = userEvent.setup();
    const onChanged = renderEditor([
      catalogQuery(),
      allocationsQuery(CAMPAIGN_ROWS),
      assignMock([{ productId: CARAMEL, quantity: 0 }]),
    ]);

    await clearAndType(`allocation-target-${CARAMEL}`, '0', user);
    await waitFor(() => expect(screen.getByTestId('save-allocations')).toBeEnabled());
    await user.click(screen.getByTestId('save-allocations'));

    // The zero matched exactly: an omitted zero would keep the four held.
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(screen.queryByText('Saved, with a warning')).not.toBeInTheDocument();
  });

  it('ALLOC-01: a product never typed, or typed exactly as it already holds, is left out of the batch', async () => {
    const user = userEvent.setup();
    const onChanged = renderEditor([
      catalogQuery(),
      allocationsQuery(CAMPAIGN_ROWS),
      assignMock([{ productId: BUTTER, quantity: 2 }]),
    ]);

    // Nothing typed: there is nothing to save, so the write is not even offered.
    expect(await screen.findByTestId('save-allocations')).toBeDisabled();

    // Butter 2 is a change; caramel re-typed at the 4 it already holds is not.
    await clearAndType(`allocation-target-${BUTTER}`, '2', user);
    await clearAndType(`allocation-target-${CARAMEL}`, '4', user);
    await waitFor(() => expect(screen.getByTestId('save-allocations')).toBeEnabled());
    await user.click(screen.getByTestId('save-allocations'));

    // The mock above matches only a batch carrying the butter row alone.
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('ALLOC-03/ALLOC-04 (SS-SM-05 step 2): the server’s overage sentence is rendered as written, and nothing was clamped', async () => {
    const user = userEvent.setup();
    const caramelWarning = {
      __typename: 'AllocationWarning',
      code: 'ASSIGNMENT_OVERAGE',
      productId: CARAMEL,
      currentStockQty: 4,
      assignedQty: 6,
      overageQty: 2,
      message: 'Only 4 Caramel Corn are in stock right now; 6 are assigned across this campaign’s events, an overage of 2.',
    };
    const butterWarning = {
      __typename: 'AllocationWarning',
      code: 'ASSIGNMENT_OVERAGE',
      productId: BUTTER,
      currentStockQty: 5,
      assignedQty: 8,
      overageQty: 3,
      message: null,
    };
    const onChanged = renderEditor([
      catalogQuery(),
      allocationsQuery(CAMPAIGN_ROWS),
      assignMock([{ productId: CARAMEL, quantity: 6 }], [caramelWarning, butterWarning]),
    ]);

    await clearAndType(`allocation-target-${CARAMEL}`, '6', user);
    await waitFor(() => expect(screen.getByTestId('save-allocations')).toBeEnabled());
    await user.click(screen.getByTestId('save-allocations'));

    // The write carried six — the mock only matches an unclamped six, because
    // a screen that "helpfully" reduced it to the 4 in stock would not match.
    await waitFor(() => expect(screen.getByTestId('overage-warnings')).toBeInTheDocument());
    expect(screen.getByText('Saved, with a warning')).toBeInTheDocument();
    expect(screen.getByTestId('overage-warnings').textContent).toMatch(/promise more than it holds for 2 products/);
    expect(screen.getByTestId(`overage-sentence-${CARAMEL}`)).toHaveTextContent(
      'Only 4 Caramel Corn are in stock right now; 6 are assigned across this campaign’s events, an overage of 2.',
    );
    // A warning with no server sentence still names the four numbers.
    expect(screen.getByTestId(`overage-sentence-${BUTTER}`)).toHaveTextContent(
      '8 assigned against 5 in stock — 3 more than the campaign holds.',
    );
    // The help beside each sentence is a real focusable control: a warning
    // only reachable by hover is unreadable by keyboard and by touch.
    expect(screen.getByRole('button', { name: `Why this product is over-assigned: ${CARAMEL}` })).toBeInTheDocument();
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('§3.2.4: 16 products past the page size are all fetched before the totals are shown', async () => {
    // The campaign's first page stops short; the sixteenth product's stock only
    // exists on the continuation. A screen that summed page one alone would
    // understate the assignment the next save is judged against.
    const firstPage = [
      allocFixture(CARAMEL, SSE, 4),
      ...Array.from({ length: 14 }, (_, index) => allocFixture(`PROD#p${index + 2}`, 'SSE#grove', 1)),
    ];
    const continuation = {
      request: {
        query: LIST_EVENT_INVENTORY_ALLOCATIONS,
        variables: { ...ALLOC_VARIABLES, page: { limit: SHOW_AND_SELL_PAGE_SIZE, cursor: 'ALLOC-CURSOR-2' } },
      },
      result: {
        data: {
          eventInventoryAllocations: {
            __typename: 'EventInventoryAllocationConnection',
            items: [allocFixture('PROD#p16', 'SSE#grove', 3)],
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      },
    };
    renderEditor(
      [catalogQuery(Array.from({ length: 16 }, (_, index) => productFixture(index + 1))), allocationsQuery(firstPage, 'ALLOC-CURSOR-2', true), continuation],
      eventFixture({ productIds: [CARAMEL] }),
    );

    const assigned = await screen.findByTestId('allocation-assigned-PROD#p16');
    await waitFor(() => expect(assigned).toHaveTextContent('3'));
    expect(screen.getAllByTestId(/^allocation-row-/)).toHaveLength(16);
  });

  it('ALLOC-08: a plan that is not a whole number is refused before any write exists', async () => {
    const user = userEvent.setup();
    // No write mock in this test at all: nothing here may reach the server.
    const onChanged = renderEditor([catalogQuery(), allocationsQuery(CAMPAIGN_ROWS)]);

    await clearAndType(`allocation-target-${CARAMEL}`, 'nine', user);
    await clearAndType(`allocation-target-${BUTTER}`, '-1', user);
    expect(await screen.findByTestId('save-allocations')).toBeDisabled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('§3.5.2: the editor is inert once the event is finalized', async () => {
    const event = eventFixture({ status: 'FINALIZED' });
    renderEditor([catalogQuery(), allocationsQuery(CAMPAIGN_ROWS)], event);

    expect(await screen.findByTestId('allocation-locked-note')).toHaveTextContent(
      'A finalized or cancelled event cannot change its allocations. Its rows stand as the history they were finalized with.',
    );
    expect(await screen.findByTestId(`allocation-target-${CARAMEL}`)).toBeDisabled();
    expect(screen.getByTestId('save-allocations')).toBeDisabled();
    expect(screen.queryByTestId('allocation-reopened-note')).not.toBeInTheDocument();
  });

  it('§3.5.2: a reopened event’s targets are a draft, and the screen says whose balances decide', async () => {
    const event = eventFixture({ status: 'REOPENED' });
    renderEditor([catalogQuery(), allocationsQuery(CAMPAIGN_ROWS)], event);

    expect(await screen.findByTestId('allocation-reopened-note')).toHaveTextContent(
      'This event is reopened: what you save here is a draft. The campaign’s stock answer belongs to re-finalization, which is what decides the real balances.',
    );
    // Still editable — the draft is real work — but nothing is typed yet, so
    // there is nothing to save.
    expect(await screen.findByTestId(`allocation-target-${CARAMEL}`)).toBeEnabled();
    expect(screen.getByTestId('save-allocations')).toBeDisabled();
    expect(screen.queryByTestId('allocation-locked-note')).not.toBeInTheDocument();
  });

  it('ALLOC-08 (VER-01): a refused save names the refusal and keeps what the admin typed', async () => {
    const user = userEvent.setup();
    const onChanged = renderEditor([
      catalogQuery(),
      allocationsQuery(CAMPAIGN_ROWS),
      {
        request: {
          query: ASSIGN_SHOW_AND_SELL_INVENTORY,
          variables: {
            input: {
              showAndSellId: SSE,
              items: [{ productId: CARAMEL, quantity: 3 }],
              version: { expectedVersion: 7 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('the concurrent-stock rule refuses six assigned against four in stock for the same window', {
          extensions: { code: 'CONFLICT' },
        }),
      },
    ]);

    await clearAndType(`allocation-target-${CARAMEL}`, '3', user);
    await waitFor(() => expect(screen.getByTestId('save-allocations')).toBeEnabled());
    await user.click(screen.getByTestId('save-allocations'));

    // SS-SM-05 step 4: the overlapping over-assignment is refused whole, with
    // no partial allocation saved, and the number the admin typed stays on the
    // screen so the next attempt can be a deliberate one.
    expect(await screen.findByText(STALE_SENTENCE)).toBeInTheDocument();
    expect(screen.getByTestId(`allocation-target-${CARAMEL}`)).toHaveValue('3');
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('§3.5.2: an allocation read that failed is not shown as an empty one', async () => {
    renderEditor([
      catalogQuery(),
      {
        request: { query: LIST_EVENT_INVENTORY_ALLOCATIONS, variables: ALLOC_VARIABLES },
        error: new GraphQLError('Service unavailable.'),
      },
    ]);

    expect(await screen.findByText('Could not load this campaign’s allocations.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
