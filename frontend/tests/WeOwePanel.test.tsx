/**
 * The We Owe board: reservation as a target, fulfillment from one source (§4.5.1).
 *
 * What each assertion pins, and why it matters:
 *
 * - The numbers on a card are the server's own arithmetic read back from the row
 *   (original / fulfilled / reserved / uncovered / remaining), never a browser
 *   re-computation, and a closed obligation is history with its reason.
 * - Reservation is a target, not an increment: the write carries the number the
 *   admin typed, and a lower number is the same write — a release. A target above
 *   what the obligation still owes is refused in the browser, so no write exists
 *   to spend its idempotency key.
 * - Fulfillment is bounded by the source (OWE-07): KERNEL_STOCK may only reach
 *   what is reserved, EXTERNAL_COUNCIL only what is uncovered. A covered portion
 *   has to be released first, and the screen refuses the overage rather than
 *   letting the server answer with a movement the Unit did not intend.
 * - Both writes carry the obligation's own version and one idempotency key, and a
 *   CONFLICT re-reads the board so the next attempt is aimed at fresh versions.
 * - The status filter is a query argument, not a browser filter: the CLOSED view
 *   asks the server for CLOSED rows.
 * - The board is cards, not a wide table, so on a phone every figure and control of
 *   an obligation is on the screen with nothing to scroll sideways to reach, and both
 *   writes are reachable and savable with Tab and Enter alone.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';
import { MockedProvider } from '@apollo/client/testing/react';
import { FULFILL_WE_OWE, LIST_WE_OWE_OBLIGATIONS, SET_WE_OWE_RESERVATION } from '../src/lib/graphql';
import { WeOwePanel } from '../src/components/showSell/WeOwePanel';
import { SHOW_AND_SELL_PAGE_SIZE } from '../src/lib/showSell';
import { clearAndType, chooseOption, focusByTab, scrollContainerOf, typeInto, withViewport } from './helpers/unitUi';
import type { GqlShowAndSellAdminFieldsFragment, GqlWeOweObligationFieldsFragment } from '../src/types/graphql-generated';

const UC = 'UNITCAMP#pack-3149-fall';
const SSE = 'SSE#library';
const UNIT = 'UNIT#pack-3149';
const ZONE = 'America/Denver';
const CARAMEL = 'PROD#caramel';

const STALE_SENTENCE =
  'That was refused because the event, a slot, or a signup has already moved. Reload this screen and try again with what it now shows.';

const ALL_VARIABLES = { unitCampaignId: UC, showAndSellId: SSE, page: { limit: SHOW_AND_SELL_PAGE_SIZE } };
const OPEN_VARIABLES = { unitCampaignId: UC, showAndSellId: SSE, status: 'OPEN', page: { limit: SHOW_AND_SELL_PAGE_SIZE } };
const CLOSED_VARIABLES = { unitCampaignId: UC, showAndSellId: SSE, status: 'CLOSED', page: { limit: SHOW_AND_SELL_PAGE_SIZE } };

let keySequence = 0;
let sent: Record<string, Record<string, unknown>[]>;

beforeEach(() => {
  keySequence = 0;
  sent = { reservation: [], fulfillment: [] };
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function obligationFixture(overrides: Partial<GqlWeOweObligationFieldsFragment> = {}): GqlWeOweObligationFieldsFragment {
  return {
    __typename: 'WeOweObligation',
    weOweId: 'WEOWE#1',
    unitCampaignId: UC,
    showAndSellId: SSE,
    saleId: 'SALE#1',
    lineItemId: 'LINE#1',
    buyerName: 'Avery',
    productId: CARAMEL,
    productNameSnapshot: 'Caramel',
    originalQty: 4,
    fulfilledQty: 0,
    cancelledQty: 0,
    reservedQty: 0,
    remainingQty: 4,
    uncoveredQty: 4,
    valueCentsSnapshot: 400,
    status: 'OPEN',
    closeReason: null,
    version: 1,
    createdAt: '2026-03-28T15:30:00.000Z',
    closedAt: null,
    ...overrides,
  };
}

function eventFixture(overrides: Partial<GqlShowAndSellAdminFieldsFragment> = {}): GqlShowAndSellAdminFieldsFragment {
  return {
    __typename: 'ShowAndSellAdmin',
    showAndSellId: SSE,
    unitId: UNIT,
    unitCampaignId: UC,
    locationName: 'Library on Main',
    address: null,
    startAt: '2026-03-28T15:00:00.000Z',
    endAt: '2026-03-28T18:30:00.000Z',
    status: 'ACTIVE',
    splitMethod: 'TIME_WORKED',
    weOweEnabled: true,
    productIds: [CARAMEL],
    allocations: [],
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

function connection(items: readonly GqlWeOweObligationFieldsFragment[]) {
  return {
    weOweObligations: {
      __typename: 'WeOweObligationConnection',
      items,
      pageInfo: { endCursor: null, hasNextPage: false },
    },
  };
}

function reservationMock(
  variables: Record<string, unknown>,
  obligation: GqlWeOweObligationFieldsFragment,
  options: { error?: GraphQLError } = {},
) {
  return {
    request: { query: SET_WE_OWE_RESERVATION, variables: { input: variables } },
    ...(options.error
      ? { error: options.error }
      : {
          result: (sentVariables: Record<string, unknown>) => {
            sent.reservation.push(sentVariables);
            return {
              data: {
                setWeOweReservation: {
                  __typename: 'SetWeOweReservationPayload',
                  obligation: { ...obligation, reservedQty: Number(variables.targetReservedQty), version: obligation.version + 1 },
                },
              },
            };
          },
        }),
  };
}

function fulfillmentMock(
  variables: Record<string, unknown>,
  obligation: GqlWeOweObligationFieldsFragment,
  options: { error?: GraphQLError } = {},
) {
  return {
    request: { query: FULFILL_WE_OWE, variables: { input: variables } },
    ...(options.error
      ? { error: options.error }
      : {
          result: (sentVariables: Record<string, unknown>) => {
            sent.fulfillment.push(sentVariables);
            const quantity = Number(variables.quantity);
            const kernel = variables.source === 'KERNEL_STOCK';
            return {
              data: {
                fulfillWeOwe: {
                  __typename: 'FulfillWeOwePayload',
                  obligation: {
                    ...obligation,
                    fulfilledQty: obligation.fulfilledQty + quantity,
                    reservedQty: kernel ? obligation.reservedQty - quantity : obligation.reservedQty,
                    uncoveredQty: kernel ? obligation.uncoveredQty : obligation.uncoveredQty - quantity,
                    remainingQty: obligation.remainingQty - quantity,
                    version: obligation.version + 1,
                  },
                  fulfillment: {
                    __typename: 'WeOweFulfillment',
                    fulfillmentId: 'FULFILL#1',
                    weOweId: obligation.weOweId,
                    quantity,
                    source: variables.source,
                    actorAccountId: 'ACCOUNT#casey',
                    createdAt: '2026-03-29T15:00:00.000Z',
                    inventoryMovementId: kernel ? 'MOVE#1' : null,
                  },
                },
              },
            };
          },
        }),
  };
}

function renderPanel(
  obligations: readonly GqlWeOweObligationFieldsFragment[],
  mutationMocks: object[] = [],
  options: { filterMocks?: boolean } = {},
) {
  const onChanged = vi.fn(async () => undefined);
  const reads = [
    { request: { query: LIST_WE_OWE_OBLIGATIONS, variables: ALL_VARIABLES }, result: { data: connection(obligations) } },
    { request: { query: LIST_WE_OWE_OBLIGATIONS, variables: OPEN_VARIABLES }, result: { data: connection(obligations) } },
    { request: { query: LIST_WE_OWE_OBLIGATIONS, variables: CLOSED_VARIABLES }, result: { data: connection([]) } },
  ];
  const selected = options.filterMocks ? reads : reads.slice(0, 1);
  render(
    <MockedProvider mocks={[...selected, ...mutationMocks] as never}>
      <WeOwePanel event={eventFixture()} timezone={ZONE} onChanged={onChanged} />
    </MockedProvider>,
  );
  return onChanged;
}

describe('the obligation rows', () => {
  it('shows the server’s own arithmetic and the counts, not a browser re-computation', async () => {
    renderPanel([
      obligationFixture({ weOweId: 'WEOWE#1', originalQty: 4, fulfilledQty: 1, reservedQty: 2, uncoveredQty: 1, remainingQty: 3 }),
      obligationFixture({
        weOweId: 'WEOWE#2',
        status: 'CLOSED',
        closeReason: 'FULFILLED',
        originalQty: 2,
        fulfilledQty: 2,
        reservedQty: 0,
        uncoveredQty: 0,
        remainingQty: 0,
      }),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await screen.findByTestId('we-owe-card-WEOWE#2');
    expect(screen.getByTestId('we-owe-counts')).toHaveTextContent('1 open · 1 closed');

    const meta = screen.getByTestId('we-owe-meta-WEOWE#1');
    expect(meta).toHaveTextContent('Original 4');
    expect(meta).toHaveTextContent('fulfilled 1');
    expect(meta).toHaveTextContent('reserved 2');
    expect(meta).toHaveTextContent('uncovered 1');
    expect(meta).toHaveTextContent('remaining 3');
    expect(screen.getByTestId('we-owe-status-WEOWE#1')).toHaveTextContent('Open');

    // A closed row is history: it names why it closed and offers no actions.
    expect(screen.getByTestId('we-owe-status-WEOWE#2')).toHaveTextContent('Closed · Fulfilled');
    expect(screen.getByTestId('we-owe-closed-WEOWE#2')).toHaveTextContent('history');
    expect(screen.queryByTestId('we-owe-save-reservation-WEOWE#2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('we-owe-fulfill-WEOWE#2')).not.toBeInTheDocument();
  });

  it('says so when there is nothing, and asks the server for the filtered view', async () => {
    const user = userEvent.setup();
    renderPanel([], [], { filterMocks: true });

    expect(await screen.findByTestId('we-owe-empty')).toHaveTextContent('No obligations yet');

    await chooseOption('we-owe-status-filter', 'Closed', user);

    expect(await screen.findByTestId('we-owe-empty')).toHaveTextContent('No closed obligations');
  });
});

describe('reservation', () => {
  it('saves a target, aimed at the obligation’s own version', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 0, uncoveredQty: 4, remainingQty: 4 });
    const onChanged = renderPanel([obligation], [
      reservationMock(
        {
          weOweId: 'WEOWE#1',
          targetReservedQty: 3,
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    const button = screen.getByTestId('we-owe-save-reservation-WEOWE#1');
    // No change, no write: the button is dead until a number is typed.
    expect(button).toBeDisabled();

    await clearAndType('we-owe-reserve-target-WEOWE#1', '3', user);
    expect(screen.getByTestId('we-owe-release-hint-WEOWE#1')).toHaveTextContent('Holds 3 Kernels');

    await user.click(button);

    await waitFor(() => expect(sent.reservation).toHaveLength(1));
    const input = sent.reservation[0].input as Record<string, unknown>;
    expect(input.weOweId).toBe('WEOWE#1');
    expect(input.targetReservedQty).toBe(3);
    expect(input.version).toEqual({ expectedVersion: 1 });
    expect(input.idempotency).toEqual({ idempotencyKey: 'test-idem-1' });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('a lower target is a release, and it is the same write', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 2, uncoveredQty: 2, remainingQty: 4 });
    const onChanged = renderPanel([obligation], [
      reservationMock(
        {
          weOweId: 'WEOWE#1',
          targetReservedQty: 0,
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await clearAndType('we-owe-reserve-target-WEOWE#1', '0', user);

    expect(screen.getByTestId('we-owe-release-hint-WEOWE#1')).toHaveTextContent('Releases 2 Kernels back to sellable stock');
    expect(screen.getByTestId('we-owe-save-reservation-WEOWE#1')).toHaveTextContent('Release the excess');

    await user.click(screen.getByTestId('we-owe-save-reservation-WEOWE#1'));

    await waitFor(() => expect(sent.reservation).toHaveLength(1));
    expect((sent.reservation[0].input as Record<string, unknown>).targetReservedQty).toBe(0);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  // One Kernel is still one Kernel, and a row the server never dated stays undated:
  // the hint the admin acts on has to read the way the number is.
  it('says the release and the hold in the singular, and leaves an undated row undated', async () => {
    const user = userEvent.setup();
    renderPanel([
      obligationFixture({ weOweId: 'WEOWE#1', reservedQty: 2, uncoveredQty: 1, remainingQty: 3, createdAt: null }),
      obligationFixture({ weOweId: 'WEOWE#2', reservedQty: 0, uncoveredQty: 3, remainingQty: 3, createdAt: null }),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#2');
    expect(screen.getByTestId('we-owe-meta-WEOWE#1')).not.toHaveTextContent('opened');
    expect(screen.getByTestId('we-owe-meta-WEOWE#2')).not.toHaveTextContent('opened');

    await clearAndType('we-owe-reserve-target-WEOWE#1', '1', user);
    expect(screen.getByTestId('we-owe-release-hint-WEOWE#1')).toHaveTextContent('Releases 1 Kernel back to sellable stock');

    await clearAndType('we-owe-reserve-target-WEOWE#2', '1', user);
    expect(screen.getByTestId('we-owe-release-hint-WEOWE#2')).toHaveTextContent('Holds 1 Kernel against this obligation');
  });

  it('refuses a target above what the obligation still owes, with no write at all', async () => {
    const user = userEvent.setup();
    renderPanel([obligationFixture({ reservedQty: 0, uncoveredQty: 4, remainingQty: 4 })]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await clearAndType('we-owe-reserve-target-WEOWE#1', '5', user);

    expect(screen.getByTestId('we-owe-error-WEOWE#1')).toHaveTextContent('owes 4 more');
    expect(screen.getByTestId('we-owe-save-reservation-WEOWE#1')).toBeDisabled();
    expect(sent.reservation).toHaveLength(0);
  });

  it('refuses a target that is not a whole number', async () => {
    const user = userEvent.setup();
    renderPanel([obligationFixture()]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await clearAndType('we-owe-reserve-target-WEOWE#1', '1.5', user);

    expect(screen.getByTestId('we-owe-error-WEOWE#1')).toHaveTextContent('whole number');
    expect(screen.getByTestId('we-owe-save-reservation-WEOWE#1')).toBeDisabled();
    expect(sent.reservation).toHaveLength(0);
  });

  it('a CONFLICT shows the stale-row sentence and re-reads the board', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 0, uncoveredQty: 4, remainingQty: 4 });
    const onChanged = renderPanel([obligation], [
      reservationMock(
        {
          weOweId: 'WEOWE#1',
          targetReservedQty: 2,
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
        { error: new GraphQLError('expectedVersion 1 does not match 3', { extensions: { code: 'CONFLICT' } }) },
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await clearAndType('we-owe-reserve-target-WEOWE#1', '2', user);
    await user.click(screen.getByTestId('we-owe-save-reservation-WEOWE#1'));

    expect(await screen.findByTestId('we-owe-error-WEOWE#1')).toHaveTextContent(STALE_SENTENCE);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });
});

describe('fulfillment', () => {
  it('records a Kernel fulfillment of a reserved quantity, bounded by what is reserved', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 3, uncoveredQty: 1, remainingQty: 4 });
    const onChanged = renderPanel([obligation], [
      fulfillmentMock(
        {
          weOweId: 'WEOWE#1',
          quantity: 2,
          source: 'KERNEL_STOCK',
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    // Kernel stock is the source a reserved obligation starts on.
    expect(screen.getByTestId('we-owe-source-WEOWE#1')).toHaveTextContent('Kernel stock (reserved)');

    await typeInto('we-owe-fulfill-qty-WEOWE#1', '2', user);
    await user.click(screen.getByTestId('we-owe-fulfill-WEOWE#1'));

    await waitFor(() => expect(sent.fulfillment).toHaveLength(1));
    const input = sent.fulfillment[0].input as Record<string, unknown>;
    expect(input.weOweId).toBe('WEOWE#1');
    expect(input.quantity).toBe(2);
    expect(input.source).toBe('KERNEL_STOCK');
    expect(input.version).toEqual({ expectedVersion: 1 });
    expect(input.idempotency).toEqual({ idempotencyKey: 'test-idem-1' });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('refuses a Kernel fulfillment beyond the reservation, and names the fix', async () => {
    const user = userEvent.setup();
    renderPanel([obligationFixture({ reservedQty: 2, uncoveredQty: 2, remainingQty: 4 })]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await typeInto('we-owe-fulfill-qty-WEOWE#1', '3', user);

    expect(screen.getByTestId('we-owe-error-WEOWE#1')).toHaveTextContent('Only 2 Kernels are reserved');
    expect(screen.getByTestId('we-owe-error-WEOWE#1')).toHaveTextContent('release the reservation first');
    expect(screen.getByTestId('we-owe-fulfill-WEOWE#1')).toBeDisabled();
    expect(sent.fulfillment).toHaveLength(0);
  });

  it('refuses a Council fulfillment of stock the Kernel already holds', async () => {
    const user = userEvent.setup();
    renderPanel([obligationFixture({ reservedQty: 3, uncoveredQty: 1, remainingQty: 4 })]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await chooseOption('we-owe-source-WEOWE#1', 'External Council (uncovered)', user);
    await typeInto('we-owe-fulfill-qty-WEOWE#1', '2', user);

    expect(screen.getByTestId('we-owe-error-WEOWE#1')).toHaveTextContent('Only 1 is uncovered');
    expect(screen.getByTestId('we-owe-fulfill-WEOWE#1')).toBeDisabled();
    expect(sent.fulfillment).toHaveLength(0);
  });

  it('a partial Council fulfillment of what is uncovered goes through', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 3, uncoveredQty: 1, remainingQty: 4 });
    renderPanel([obligation], [
      fulfillmentMock(
        {
          weOweId: 'WEOWE#1',
          quantity: 1,
          source: 'EXTERNAL_COUNCIL',
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await chooseOption('we-owe-source-WEOWE#1', 'External Council (uncovered)', user);
    await typeInto('we-owe-fulfill-qty-WEOWE#1', '1', user);
    await user.click(screen.getByTestId('we-owe-fulfill-WEOWE#1'));

    await waitFor(() => expect(sent.fulfillment).toHaveLength(1));
    expect((sent.fulfillment[0].input as Record<string, unknown>).source).toBe('EXTERNAL_COUNCIL');
  });

  it('an obligation with nothing reserved and nothing uncovered offers no source', async () => {
    renderPanel([obligationFixture({ reservedQty: 0, uncoveredQty: 0, remainingQty: 0, fulfilledQty: 4 })]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    expect(screen.getByTestId('we-owe-no-source-WEOWE#1')).toHaveTextContent('No source');
    expect(screen.getByTestId('we-owe-fulfill-WEOWE#1')).toBeDisabled();
  });

  it('refuses a quantity beyond what the obligation still owes', async () => {
    const user = userEvent.setup();
    renderPanel([obligationFixture({ reservedQty: 2, uncoveredQty: 0, remainingQty: 2 })]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await typeInto('we-owe-fulfill-qty-WEOWE#1', '3', user);

    expect(screen.getByTestId('we-owe-error-WEOWE#1')).toHaveTextContent('owes 2 more');
    expect(sent.fulfillment).toHaveLength(0);
  });

  it('a CONFLICT on fulfillment shows the stale sentence and re-reads the board', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 3, uncoveredQty: 1, remainingQty: 4 });
    const onChanged = renderPanel([obligation], [
      fulfillmentMock(
        {
          weOweId: 'WEOWE#1',
          quantity: 2,
          source: 'KERNEL_STOCK',
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
        { error: new GraphQLError('expectedVersion 1 does not match 3', { extensions: { code: 'CONFLICT' } }) },
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await typeInto('we-owe-fulfill-qty-WEOWE#1', '2', user);
    await user.click(screen.getByTestId('we-owe-fulfill-WEOWE#1'));

    expect(await screen.findByTestId('we-owe-error-WEOWE#1')).toHaveTextContent(STALE_SENTENCE);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('spends the intent: a reservation followed by a fulfillment carries two different keys', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 2, uncoveredQty: 2, remainingQty: 4 });
    renderPanel([obligation], [
      reservationMock(
        {
          weOweId: 'WEOWE#1',
          targetReservedQty: 3,
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
      ),
      fulfillmentMock(
        {
          weOweId: 'WEOWE#1',
          quantity: 2,
          source: 'KERNEL_STOCK',
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-2' },
        },
        obligation,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    await clearAndType('we-owe-reserve-target-WEOWE#1', '3', user);
    await user.click(screen.getByTestId('we-owe-save-reservation-WEOWE#1'));
    await waitFor(() => expect(sent.reservation).toHaveLength(1));

    await typeInto('we-owe-fulfill-qty-WEOWE#1', '2', user);
    await user.click(screen.getByTestId('we-owe-fulfill-WEOWE#1'));
    await waitFor(() => expect(sent.fulfillment).toHaveLength(1));

    expect((sent.reservation[0].input as Record<string, unknown>).idempotency).toEqual({ idempotencyKey: 'test-idem-1' });
    expect((sent.fulfillment[0].input as Record<string, unknown>).idempotency).toEqual({ idempotencyKey: 'test-idem-2' });
  });
});

describe('the source rule after review', () => {
  it('plans against the source the card actually offers, not the blank draft choice', async () => {
    const user = userEvent.setup();
    const obligation = obligationFixture({ reservedQty: 0, uncoveredQty: 3, remainingQty: 3 });
    renderPanel([obligation], [
      fulfillmentMock(
        {
          weOweId: 'WEOWE#1',
          quantity: 1,
          source: 'EXTERNAL_COUNCIL',
          version: { expectedVersion: 1 },
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
        obligation,
      ),
    ]);

    await screen.findByTestId('we-owe-card-WEOWE#1');
    // Only Council is offered here, so the card starts on it and the Kernel bound never applies.
    expect(screen.getByTestId('we-owe-source-WEOWE#1')).toHaveTextContent('External Council (uncovered)');

    await typeInto('we-owe-fulfill-qty-WEOWE#1', '1', user);
    expect(screen.queryByTestId('we-owe-error-WEOWE#1')).toBeNull();
    expect(screen.getByTestId('we-owe-fulfill-WEOWE#1')).toBeEnabled();

    await user.click(screen.getByTestId('we-owe-fulfill-WEOWE#1'));

    await waitFor(() => expect(sent.fulfillment).toHaveLength(1));
    expect((sent.fulfillment[0].input as Record<string, unknown>).source).toBe('EXTERNAL_COUNCIL');
  });
});

// ---------------------------------------------------------------------------------------------
// §4.5.1: the board on a phone, and with the keyboard alone
// ---------------------------------------------------------------------------------------------

describe('§4.5.1: the board on a 390-pixel viewport', () => {
  /*
   * Reservation and fulfillment happen on the floor, where the Kernel holding the
   * obligation is the one standing at the shelf with a phone. A board that only works
   * on a desktop is a promise the Unit cannot keep where it is kept. Unlike the sales
   * list, these obligations are cards stacked in one column, so a phone does not cut a
   * figure off — the tests here prove the absence of anything to scroll sideways to,
   * and that a Kernel who does not use a pointer reaches both writes with Tab.
   */

  it('shows every figure and control of an obligation with nothing to scroll sideways to', async () => {
    await withViewport(390, async () => {
      renderPanel([obligationFixture({ reservedQty: 2, uncoveredQty: 2 })]);
      await screen.findByTestId('we-owe-card-WEOWE#1');

      // The shape that would make a figure fall off the edge: a wide table, or a card
      // parked inside a horizontal scroller of its own.
      expect(screen.queryByRole('table')).toBeNull();
      expect(scrollContainerOf(screen.getByTestId('we-owe-card-WEOWE#1'))).toBeNull();

      for (
        const id of [
          'we-owe-product-WEOWE#1',
          'we-owe-buyer-WEOWE#1',
          'we-owe-status-WEOWE#1',
          'we-owe-reserve-target-WEOWE#1',
          'we-owe-save-reservation-WEOWE#1',
          'we-owe-fulfill-qty-WEOWE#1',
          'we-owe-source-WEOWE#1',
          'we-owe-fulfill-WEOWE#1',
        ]
      ) {
        expect(screen.getByTestId(id), `${id} is not shown at 390 pixels`).toBeVisible();
      }
    });
  });

  it('sets a reservation with Tab and Enter alone, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      const obligation = obligationFixture({ reservedQty: 0, uncoveredQty: 4, remainingQty: 4 });
      renderPanel([obligation], [
        reservationMock(
          {
            weOweId: 'WEOWE#1',
            targetReservedQty: 3,
            version: { expectedVersion: 1 },
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
          obligation,
        ),
      ]);
      await screen.findByTestId('we-owe-card-WEOWE#1');

      await clearAndType('we-owe-reserve-target-WEOWE#1', '3', user);
      await focusByTab(screen.getByTestId('we-owe-save-reservation-WEOWE#1'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(sent.reservation).toHaveLength(1));
      const input = sent.reservation[0].input as Record<string, unknown>;
      expect(input.targetReservedQty).toBe(3);
      expect(input.idempotency).toEqual({ idempotencyKey: 'test-idem-1' });
    });
  });

  it('records a fulfillment with Tab and Enter alone, on a 390-pixel viewport', async () => {
    const user = userEvent.setup();
    await withViewport(390, async () => {
      const obligation = obligationFixture({ reservedQty: 4, uncoveredQty: 0 });
      renderPanel([obligation], [
        fulfillmentMock(
          {
            weOweId: 'WEOWE#1',
            quantity: 2,
            source: 'KERNEL_STOCK',
            version: { expectedVersion: 1 },
            idempotency: { idempotencyKey: 'test-idem-1' },
          },
          obligation,
        ),
      ]);
      await screen.findByTestId('we-owe-card-WEOWE#1');

      await typeInto('we-owe-fulfill-qty-WEOWE#1', '2', user);
      // The source picker sits between the quantity and the write, and Tab walks past it
      // without the picker being opened — the card started on the only legal source.
      await focusByTab(screen.getByTestId('we-owe-fulfill-WEOWE#1'), user);
      await user.keyboard('{Enter}');

      await waitFor(() => expect(sent.fulfillment).toHaveLength(1));
      const input = sent.fulfillment[0].input as Record<string, unknown>;
      expect(input.quantity).toBe(2);
      expect(input.source).toBe('KERNEL_STOCK');
    });
  });

  it('keeps a closed obligation readable and inert at phone width', async () => {
    await withViewport(390, async () => {
      renderPanel([obligationFixture({ status: 'CLOSED', closeReason: 'FULFILLED', fulfilledQty: 4, reservedQty: 4, uncoveredQty: 0, remainingQty: 0 })]);

      const card = await screen.findByTestId('we-owe-card-WEOWE#1');
      expect(card).toHaveTextContent('history');
      expect(card).toBeVisible();
      expect(scrollContainerOf(card)).toBeNull();
      expect(screen.queryByTestId('we-owe-save-reservation-WEOWE#1')).toBeNull();
    });
  });
});
