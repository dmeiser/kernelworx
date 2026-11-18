/**
 * Receipt, stock-only adjustment, Council on order, positions, and movement history
 * (Show & Sell §2.6.1, `SS-SM-03` value and filter cases).
 *
 * Two things this suite exists to keep true:
 *
 * The balance columns are the server's. Sellable, assigned, unassigned, overage, With
 * Scout, and total unit-owned stock are fields the server computed from the balance row
 * plus the open allocations and custody rows, and the screen renders them verbatim — it
 * has no arithmetic of its own that could state a number the audit trail does not
 * support.
 *
 * A stock change is stock only (`INV-03`). The screen says so where the write is
 * offered, because an admin who uses a stock adjustment to record money gets a figure
 * that can never be reconciled against the cash.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { InventoryPanel } from '../src/components/InventoryPanel';
import {
  ADJUST_COUNCIL_ON_ORDER,
  ADJUST_INVENTORY,
  GET_INVENTORY_MOVEMENTS,
  GET_INVENTORY_POSITIONS,
  GET_UNIT_CAMPAIGN_CATALOG,
  RECORD_INVENTORY_RECEIPT,
} from '../src/lib/graphql';
import { INVENTORY_PAGE_SIZE, MAX_QUANTITY, STOCK_ONLY_NOTE } from '../src/lib/inventory';
import { chooseOption, clearAndType, clearField, typeInto } from './helpers/unitUi';

const UC = 'UNITCAMP#pack-3149-fall';
const CARAMEL = 'PROD#caramel';
const BUTTER = 'PROD#butter';

const POSITION_VARIABLES = { unitCampaignId: UC, productIds: [CARAMEL, BUTTER], page: { limit: INVENTORY_PAGE_SIZE } };
const MOVEMENT_VARIABLES = {
  unitCampaignId: UC,
  productId: undefined,
  movementType: undefined,
  profileId: undefined,
  dateRange: undefined,
  page: { limit: INVENTORY_PAGE_SIZE },
};

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

/**
 * One product's position, in the shape SS-SM-03 seeds: 14 Caramel received, 4 of them
 * issued to a Scout, so 10 are sellable and 4 are With Scout. The derived columns are
 * what the server answered, and the test says so by asserting them unchanged.
 */
function positionFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'InventoryPosition',
    unitCampaignId: UC,
    productId: CARAMEL,
    kernelPhysicalQty: 14,
    soldInPossessionQty: 0,
    councilOnOrderQty: 0,
    version: 3,
    createdAt: '2026-02-01T15:00:00Z',
    updatedAt: '2026-02-05T15:00:00Z',
    sellableKernelQty: 10,
    assignedOpenQty: 0,
    unassignedKernelQty: 10,
    assignmentOverageQty: 0,
    withScoutQty: 4,
    totalUnitOwnedUndeliveredQty: 14,
    ...overrides,
  };
}

const caramel = () => positionFixture();
const butter = () =>
  positionFixture({
    productId: BUTTER,
    kernelPhysicalQty: 24,
    sellableKernelQty: 14,
    unassignedKernelQty: 14,
    withScoutQty: 10,
    totalUnitOwnedUndeliveredQty: 24,
    councilOnOrderQty: 6,
    version: 5,
  });

function positionsQuery(items: unknown[], pageInfo: Record<string, unknown> = { endCursor: null, hasNextPage: false }) {
  return {
    request: { query: GET_INVENTORY_POSITIONS, variables: POSITION_VARIABLES },
    result: {
      data: {
        inventoryPositions: {
          __typename: 'InventoryPositionConnection',
          items,
          pageInfo: { __typename: 'PageInfo', ...pageInfo },
        },
      },
    },
  };
}

const catalogQuery = {
  request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: UC } },
  result: {
    data: {
      unitCampaignCatalog: {
        __typename: 'UnitCampaignCatalog',
        catalogId: 'CATALOG#fall',
        catalogName: 'Fall catalog',
        products: [
          {
            __typename: 'CatalogProduct',
            productId: CARAMEL,
            productName: 'Caramel Corn',
            description: null,
            price: 6,
            sortOrder: 1,
          },
          {
            __typename: 'CatalogProduct',
            productId: BUTTER,
            productName: 'Butter Popcorn',
            description: null,
            price: 6,
            sortOrder: 2,
          },
        ],
      },
    },
  },
};

function movementFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'InventoryMovement',
    movementId: 'MOVE#receipt-1',
    unitCampaignId: UC,
    productId: CARAMEL,
    movementType: 'RECEIPT',
    kernelPhysicalDelta: 14,
    soldPossessionDelta: 0,
    withScoutDelta: 0,
    assignedDelta: 0,
    councilOnOrderDelta: 0,
    profileId: null,
    showAndSellId: null,
    orderId: null,
    fulfillmentId: null,
    reason: null,
    actorAccountId: 'ACCOUNT#avery',
    occurredAt: '2026-02-01T15:00:00Z',
    idempotencyKey: 'receipt-1',
    inventoryVersion: 1,
    ...overrides,
  };
}

function movementsQuery(items: unknown[], variables: Record<string, unknown> = MOVEMENT_VARIABLES) {
  return {
    request: { query: GET_INVENTORY_MOVEMENTS, variables },
    result: {
      data: {
        inventoryMovements: {
          __typename: 'InventoryMovementConnection',
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
      <InventoryPanel unitCampaignId={UC} />
    </MockedProvider>,
  );
}

/** Nothing on this screen is refusing: the stock-only note is an alert too, so role alone is not the test. */
async function expectNoRefusal() {
  await waitFor(() => expect(screen.queryByTestId('form-dialog-confirm')).not.toBeInTheDocument());
  expect(screen.queryByText(/refused|could not be/)).not.toBeInTheDocument();
}

/** Opens one of the three stock dialogs, once the catalog has made the write possible. */
async function openAction(testId: string, user: ReturnType<typeof userEvent.setup>) {
  const button = await screen.findByTestId(testId);
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
}

async function fillStock(productId: string, quantity: string, user: ReturnType<typeof userEvent.setup>) {
  await chooseOption('stock-product', productId === CARAMEL ? 'Caramel Corn' : 'Butter Popcorn', user);
  if (quantity === '') {
    await clearField('stock-quantity', user);
    return;
  }
  await clearAndType('stock-quantity', quantity, user);
}

describe('InventoryPanel', () => {
  it('shows every derived balance the server computed, beside the stock it is derived from', async () => {
    renderPanel([catalogQuery, positionsQuery([caramel(), butter()]), movementsQuery([])]);

    const row = await screen.findByTestId(`position-row-${CARAMEL}`);
    expect(within(row).getByTestId(`position-kernel-${CARAMEL}`)).toHaveTextContent('14');
    expect(within(row).getByTestId(`position-sellable-${CARAMEL}`)).toHaveTextContent('10');
    expect(within(row).getByTestId(`position-unassigned-${CARAMEL}`)).toHaveTextContent('10');
    expect(within(row).getByTestId(`position-with-scout-${CARAMEL}`)).toHaveTextContent('4');
    expect(within(row).getByTestId(`position-owned-${CARAMEL}`)).toHaveTextContent('14');
    expect(within(row).getByTestId(`position-version-${CARAMEL}`)).toHaveTextContent('v3');

    const butterRow = screen.getByTestId(`position-row-${BUTTER}`);
    expect(within(butterRow).getByTestId(`position-kernel-${BUTTER}`)).toHaveTextContent('24');
    expect(within(butterRow).getByTestId(`position-on-order-${BUTTER}`)).toHaveTextContent('6');
    expect(screen.getByTestId('position-count')).toHaveTextContent('2 products in this campaign');
  });

  it('names an assignment overage instead of hiding it in a total', async () => {
    renderPanel([
      catalogQuery,
      positionsQuery([positionFixture({ assignmentOverageQty: 3, assignedOpenQty: 17, sellableKernelQty: 0 })]),
      movementsQuery([]),
    ]);

    expect(await screen.findByTestId(`position-overage-${CARAMEL}`)).toHaveTextContent('3');
  });

  it('says a stock change is stock only, where the write is offered', async () => {
    renderPanel([catalogQuery, positionsQuery([caramel()]), movementsQuery([])]);

    const note = await screen.findByTestId('stock-only-note');
    expect(note).toHaveTextContent(STOCK_ONLY_NOTE);
    expect(note.textContent).toContain('no order, sale, payment, trade record, fulfillment, or Scout credit');

    await openAction('record-receipt', userEvent.setup());
    expect(screen.getByTestId('stock-only-note')).toBeInTheDocument();
  });

  it('records a receipt and shows the balance that write moved', async () => {
    const user = userEvent.setup();
    renderPanel([
      catalogQuery,
      positionsQuery([positionFixture({ kernelPhysicalQty: 0, sellableKernelQty: 0, unassignedKernelQty: 0, withScoutQty: 0, totalUnitOwnedUndeliveredQty: 0, version: 0 })]),
      movementsQuery([]),
      {
        request: {
          query: RECORD_INVENTORY_RECEIPT,
          variables: {
            input: { unitCampaignId: UC, productId: CARAMEL, quantity: 14, idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { recordInventoryReceipt: positionFixture({ kernelPhysicalQty: 14, version: 1 }) } },
      },
      positionsQuery([caramel()]),
    ]);

    await openAction('record-receipt', user);
    await fillStock(CARAMEL, '14', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`position-kernel-${CARAMEL}`)).toHaveTextContent('14'));
    await expectNoRefusal();
  });

  it('moves the movement trail with the stock it just changed', async () => {
    const user = userEvent.setup();
    renderPanel([
      catalogQuery,
      positionsQuery([
        positionFixture({
          kernelPhysicalQty: 0,
          sellableKernelQty: 0,
          unassignedKernelQty: 0,
          withScoutQty: 0,
          totalUnitOwnedUndeliveredQty: 0,
          version: 0,
        }),
      ]),
      // The trail answers empty at mount, and the second read is the one the write has
      // to earn: without it the list keeps its mount-time answer and the receipt the
      // admin just recorded is nowhere in the audit trail they are looking at.
      movementsQuery([]),
      {
        request: {
          query: RECORD_INVENTORY_RECEIPT,
          variables: {
            input: {
              unitCampaignId: UC,
              productId: CARAMEL,
              quantity: 14,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { recordInventoryReceipt: positionFixture({ kernelPhysicalQty: 14, version: 1 }) } },
      },
      positionsQuery([caramel()]),
      movementsQuery([movementFixture()]),
    ]);

    expect(await screen.findByTestId('movement-count')).toHaveTextContent('0 movements');

    await openAction('record-receipt', user);
    await fillStock(CARAMEL, '14', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`position-kernel-${CARAMEL}`)).toHaveTextContent('14'));
    // The filters the admin applied stay applied: the re-read is the same request, so the
    // cursor it issued still belongs to it.
    expect(await screen.findByTestId('movement-row-MOVE#receipt-1', undefined, { timeout: 2000 })).toBeInTheDocument();
    expect(screen.getByTestId('movement-count')).toHaveTextContent('1 movement');
  });

  it('refuses the shapes an unsigned quantity field will not take, before any write is sent', async () => {
    const user = userEvent.setup();
    // No write mock in either of these two tests: nothing here may reach the server.
    renderPanel([catalogQuery, positionsQuery([caramel()]), movementsQuery([])]);

    // A receipt reads from zero upward.
    await openAction('record-receipt', user);
    await fillStock(CARAMEL, '2.5', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a whole number.')).toBeInTheDocument();

    await fillStock(CARAMEL, 'two', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a whole number.')).toBeInTheDocument();

    await fillStock(CARAMEL, '', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a quantity.')).toBeInTheDocument();

    // An unsigned field takes no sign at all, so a negative is refused as a shape,
    // in the same words a fraction is — and the dialog stays open with what was typed.
    await fillStock(CARAMEL, '-3', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a whole number.')).toBeInTheDocument();
    expect(screen.queryByTestId('form-dialog-confirm')).toBeInTheDocument();
  });

  it('refuses the shapes a signed change field will not take, in its own words', async () => {
    const user = userEvent.setup();
    renderPanel([catalogQuery, positionsQuery([caramel()]), movementsQuery([])]);

    await openAction('adjust-stock', user);
    await fillStock(CARAMEL, '2.5', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a whole number, positive or negative.')).toBeInTheDocument();

    await fillStock(CARAMEL, '-2.5', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a whole number, positive or negative.')).toBeInTheDocument();

    await fillStock(CARAMEL, '0', user);
    await typeInto('stock-reason', 'bin miscount', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a change other than zero.')).toBeInTheDocument();

    await fillStock(CARAMEL, `-${MAX_QUANTITY + 1}`, user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText(`Enter a change between -${MAX_QUANTITY} and ${MAX_QUANTITY}.`)).toBeInTheDocument();
  });

  it('will not adjust stock without the reason the audit trail needs', async () => {
    const user = userEvent.setup();
    renderPanel([catalogQuery, positionsQuery([caramel()]), movementsQuery([])]);

    await openAction('adjust-stock', user);
    await fillStock(CARAMEL, '-2', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByText('Say why the stock changed.')).toBeInTheDocument();
    expect(screen.getByTestId('stock-reason')).toBeInTheDocument();
  });

  it('refuses to write a change it cannot name a product for, and lets the admin put the refusal away', async () => {
    const user = userEvent.setup();
    renderPanel([catalogQuery, positionsQuery([caramel()]), movementsQuery([])]);

    await openAction('record-receipt', user);
    await clearAndType('stock-quantity', '4', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Choose a product.')).toBeInTheDocument();
    // The refusal can be dismissed without losing the dialog: the admin was mid-form.
    await user.click(within(dialog).getByRole('button', { name: 'Close' }));
    expect(within(dialog).queryByText('Choose a product.')).not.toBeInTheDocument();
    expect(screen.getByTestId('form-dialog-confirm')).toBeInTheDocument();
  });

  it('lets a Council on-order expectation fall to zero, and asks for no reason to do it', async () => {
    const user = userEvent.setup();
    renderPanel([
      catalogQuery,
      positionsQuery([butter()]),
      movementsQuery([]),
      {
        request: {
          query: ADJUST_COUNCIL_ON_ORDER,
          variables: {
            input: {
              unitCampaignId: UC,
              productId: BUTTER,
              quantityDelta: -6,
              reason: '',
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { adjustCouncilOnOrder: butter() } },
      },
      positionsQuery([positionFixture({ productId: BUTTER, councilOnOrderQty: 0 })]),
    ]);

    await openAction('adjust-on-order', user);
    await fillStock(BUTTER, '-6', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`position-on-order-${BUTTER}`)).toHaveTextContent('0'));
    await expectNoRefusal();
  });

  it('replays one intent when a refused adjustment is confirmed again', async () => {
    const user = userEvent.setup();
    const body = {
      unitCampaignId: UC,
      productId: CARAMEL,
      quantityDelta: -2,
      reason: 'bin miscount',
      idempotency: { idempotencyKey: 'test-idem-1' },
    };
    renderPanel([
      catalogQuery,
      positionsQuery([caramel()]),
      movementsQuery([]),
      {
        request: { query: ADJUST_INVENTORY, variables: { input: body } },
        error: new GraphQLError('Kernel stock would go below what We Owe holds.', { extensions: { code: 'CONFLICT' } }),
      },
      // A refusal leaves the dialog open with what the admin typed still in it, and
      // the second confirmation carries the same key: the server replays the
      // original intent instead of counting the change twice.
      {
        request: { query: ADJUST_INVENTORY, variables: { input: body } },
        result: { data: { adjustInventory: positionFixture({ kernelPhysicalQty: 12, version: 4 }) } },
      },
      positionsQuery([positionFixture({ kernelPhysicalQty: 12, version: 4 })]),
    ]);

    await openAction('adjust-stock', user);
    await fillStock(CARAMEL, '-2', user);
    await typeInto('stock-reason', 'bin miscount', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByText(/stock or a version has already moved/)).toBeInTheDocument();
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`position-kernel-${CARAMEL}`)).toHaveTextContent('12'));
  });

  it('says what the server said when a write is refused for a reason it named', async () => {
    const user = userEvent.setup();
    renderPanel([
      catalogQuery,
      positionsQuery([caramel()]),
      movementsQuery([]),
      {
        request: {
          query: ADJUST_INVENTORY,
          variables: {
            input: {
              unitCampaignId: UC,
              productId: CARAMEL,
              quantityDelta: -2,
              reason: 'damage',
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('Kernel stock cannot go below zero.'),
      },
      positionsQuery([caramel()]),
    ]);

    await openAction('adjust-stock', user);
    await fillStock(CARAMEL, '-2', user);
    await typeInto('stock-reason', 'damage', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByText('Kernel stock cannot go below zero.')).toBeInTheDocument();
    expect(screen.getByTestId(`position-kernel-${CARAMEL}`)).toHaveTextContent('14');
  });

  it('filters the movement history to what the admin named', async () => {
    const user = userEvent.setup();
    const issue = movementFixture({
      movementId: 'MOVE#issue-1',
      movementType: 'SCOUT_ISSUE',
      kernelPhysicalDelta: -4,
      withScoutDelta: 4,
      profileId: 'PROFILE#devon',
      reason: null,
    });
    renderPanel([
      catalogQuery,
      positionsQuery([caramel()]),
      movementsQuery([]),
      movementsQuery([issue], { ...MOVEMENT_VARIABLES, productId: CARAMEL }),
      movementsQuery([issue], { ...MOVEMENT_VARIABLES, productId: CARAMEL, movementType: 'SCOUT_ISSUE' }),
      movementsQuery([issue], {
        ...MOVEMENT_VARIABLES,
        productId: CARAMEL,
        movementType: 'SCOUT_ISSUE',
        profileId: 'PROFILE#devon',
      }),
      movementsQuery([issue], {
        ...MOVEMENT_VARIABLES,
        productId: CARAMEL,
        movementType: 'SCOUT_ISSUE',
        profileId: 'PROFILE#devon',
        dateRange: { startAt: '2026-02-01T00:00:00.000Z', endAt: '2026-02-09T23:59:59.000Z' },
      }),
    ]);

    expect(await screen.findByText('No movements match these filters.')).toBeInTheDocument();

    await chooseOption('movement-filter-product', 'Caramel Corn', user);
    await user.click(screen.getByTestId('movement-filter-apply'));
    expect(await screen.findByTestId('movement-row-MOVE#issue-1')).toBeInTheDocument();
    expect(screen.getByTestId('movement-count')).toHaveTextContent('1 movement');

    await chooseOption('movement-filter-type', 'Issued to Scout', user);
    await user.click(screen.getByTestId('movement-filter-apply'));
    expect(await screen.findByTestId('movement-type-MOVE#issue-1')).toHaveTextContent('Issued to Scout');

    await typeInto('movement-filter-scout', 'PROFILE#devon', user);
    await user.click(screen.getByTestId('movement-filter-apply'));
    expect(await screen.findByTestId('movement-delta-MOVE#issue-1')).toHaveTextContent('-4 Kernel · +4 With Scout');

    await typeInto('movement-filter-from', '2026-02-01', user);
    await typeInto('movement-filter-to', '2026-02-09', user);
    await user.click(screen.getByTestId('movement-filter-apply'));
    expect(await screen.findByTestId('movement-actor-MOVE#issue-1')).toHaveTextContent('ACCOUNT#avery');
  });

  it('refuses a movement window it would not be answered', async () => {
    const user = userEvent.setup();
    renderPanel([catalogQuery, positionsQuery([caramel()]), movementsQuery([])]);

    await typeInto('movement-filter-from', '2026-02-09', user);
    await typeInto('movement-filter-to', '2026-02-01', user);
    await user.click(screen.getByTestId('movement-filter-apply'));

    expect(await screen.findByText('The end date must be after the start date.')).toBeInTheDocument();
  });

  it('names the reason a movement carries and the dash when it carries none', async () => {
    renderPanel([
      catalogQuery,
      positionsQuery([caramel()]),
      movementsQuery([
        movementFixture({ movementId: 'MOVE#adjust-1', movementType: 'STOCK_ADJUSTMENT', reason: 'bin miscount' }),
        movementFixture({ movementId: 'MOVE#sale-1', movementType: 'EVENT_IMMEDIATE_SALE', productId: BUTTER, kernelPhysicalDelta: -1 }),
        // A moment the browser cannot read is shown as the server wrote it, never as
        // `Invalid Date` in an audit line.
        movementFixture({ movementId: 'MOVE#odd-1', occurredAt: 'when the snowplow came' }),
      ]),
    ]);

    expect(await screen.findByTestId('movement-reason-MOVE#adjust-1')).toHaveTextContent('bin miscount');
    expect(screen.getByTestId('movement-reason-MOVE#sale-1')).toHaveTextContent('—');
    expect(screen.getByTestId('movement-delta-MOVE#sale-1')).toHaveTextContent('-1 Kernel');
    expect(screen.getByTestId('movement-when-MOVE#odd-1')).toHaveTextContent('when the snowplow came');
  });

  it('walks the position cursor, so the board is the whole campaign and not page one', async () => {
    renderPanel([
      catalogQuery,
      movementsQuery([]),
      positionsQuery([caramel()], { endCursor: 'position-cursor-2', hasNextPage: true }),
      {
        request: {
          query: GET_INVENTORY_POSITIONS,
          variables: {
            unitCampaignId: UC,
            productIds: [CARAMEL, BUTTER],
            page: { limit: INVENTORY_PAGE_SIZE, cursor: 'position-cursor-2' },
          },
        },
        result: {
          data: {
            inventoryPositions: {
              __typename: 'InventoryPositionConnection',
              items: [butter()],
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
      },
    ]);

    expect(await screen.findByTestId(`position-row-${CARAMEL}`)).toBeInTheDocument();
    expect(await screen.findByTestId(`position-row-${BUTTER}`)).toBeInTheDocument();
  });

  it('a board that failed to read is not shown as an empty one', async () => {
    renderPanel([
      catalogQuery,
      movementsQuery([]),
      { request: { query: GET_INVENTORY_POSITIONS, variables: POSITION_VARIABLES }, error: new GraphQLError('offline') },
    ]);

    // The board read starts only once the catalog has answered, so its failure lands a
    // round trip after mount: the wait is stated rather than assumed.
    expect(await screen.findByText("Could not load this campaign's stock.", undefined, { timeout: 2000 })).toBeInTheDocument();
  });

  it('has nothing to receive when the campaign has no catalog', async () => {
    renderPanel([
      { request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: UC } }, result: { data: { unitCampaignCatalog: null } } },
      positionsQuery([]),
      movementsQuery([]),
    ]);

    expect(await screen.findByTestId('no-catalog-note')).toBeInTheDocument();
    expect(screen.getByTestId('record-receipt')).toBeDisabled();
    expect(await screen.findByTestId('position-count')).toHaveTextContent('0 products in this campaign');
  });

  it('refuses a Council on-order change of zero before anything is written', async () => {
    const user = userEvent.setup();
    renderPanel([catalogQuery, movementsQuery([]), positionsQuery([caramel(), butter()])]);

    await openAction('adjust-on-order', user);
    await fillStock(BUTTER, '0', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    // The server requires a non-zero delta, so the field refuses zero in its own words and
    // no mutation is sent: a zero movement would sit in the trail explaining nothing. The
    // dialog stays open with what it got, because the admin has a number to change.
    expect(await screen.findByText('Enter a change other than zero.')).toBeInTheDocument();
    expect(screen.getByTestId('form-dialog-confirm')).toBeInTheDocument();
  });

  it('names every catalog product to the position read, in chunks the read accepts', async () => {
    // The read answers a product with no balance row at zeros only when it is named, and
    // it names at most 15 per call, so a 16-product catalog is read as 15 plus 1: a board
    // that stopped at the first chunk would hide the last product entirely.
    const wide = Array.from({ length: 16 }, (_, index) => ({
      __typename: 'CatalogProduct',
      productId: `PROD#p${index}`,
      productName: `Product ${index}`,
      description: null,
      price: 6,
      sortOrder: index,
    }));
    const firstFifteen = wide.slice(0, 15).map((product) => product.productId);
    renderPanel([
      {
        request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: UC } },
        result: {
          data: {
            unitCampaignCatalog: {
              __typename: 'UnitCampaignCatalog',
              catalogId: 'CATALOG#wide',
              catalogName: 'Wide catalog',
              products: wide,
            },
          },
        },
      },
      movementsQuery([]),
      {
        request: {
          query: GET_INVENTORY_POSITIONS,
          variables: { unitCampaignId: UC, productIds: firstFifteen, page: { limit: INVENTORY_PAGE_SIZE } },
        },
        result: {
          data: {
            inventoryPositions: {
              __typename: 'InventoryPositionConnection',
              items: firstFifteen.map((productId) => positionFixture({ productId })),
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
      },
      // The product nothing has ever been received for: the server answered it because the
      // read named it, and the board shows it at zeros rather than hiding it.
      {
        request: {
          query: GET_INVENTORY_POSITIONS,
          variables: { unitCampaignId: UC, productIds: ['PROD#p15'], page: { limit: INVENTORY_PAGE_SIZE } },
        },
        result: {
          data: {
            inventoryPositions: {
              __typename: 'InventoryPositionConnection',
              items: [positionFixture({ productId: 'PROD#p15', kernelPhysicalQty: 0, sellableKernelQty: 0, unassignedKernelQty: 0, withScoutQty: 0, totalUnitOwnedUndeliveredQty: 0, version: 0 })],
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
      },
    ]);

    expect(await screen.findByTestId('position-count')).toHaveTextContent('16 products in this campaign');
    expect(await screen.findByTestId('position-row-PROD#p15')).toBeInTheDocument();
  });
});
