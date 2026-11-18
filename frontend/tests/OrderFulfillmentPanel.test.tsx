/**
 * Individual Order custody consumption and fulfillment (Show & Sell §2.6.3, `SS-SM-04`).
 *
 * The rules this suite holds the screen to are the ones the server also enforces, and
 * each has a failure mode a screen can introduce on its own:
 *
 * - a door-to-door sale is never refused for wanting stock, so the shortfall has to be
 *   *visible* on the line rather than lost;
 * - every fulfillment and reversal carries the `fulfillmentVersion` this screen just
 *   read, and the line it names by `lineItemId`, because two admins looking at one Order
 *   must not both fill the same last Kernel;
 * - at most one reversal exists per fulfillment, and the screen reads that off the
 *   history so a second Reverse is never offered;
 * - the Scout's own view is a different document, with no actor account and no inventory
 *   movement id in it, so the audit fields cannot reach it by accident.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { OrderFulfillmentPanel } from '../src/components/OrderFulfillmentPanel';
import {
  FULFILL_INDIVIDUAL_ORDER_LINE,
  GET_ORDER_FULFILLMENTS,
  GET_PARTICIPANT_ORDER_FULFILLMENTS,
  GET_UNIT_CAMPAIGN_CATALOG,
  LIST_UNIT_CAMPAIGN_ROSTER,
  LIST_UNIT_SCOUT_ORDERS,
  RECORD_CUSTODY_SALE,
  REVERSE_INDIVIDUAL_ORDER_FULFILLMENT,
} from '../src/lib/graphql';
import { ORDER_PAGE_SIZE, fulfillmentSourceLabel, page } from '../src/lib/inventory';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { chooseOption, clearAndType, clearField, typeInto } from './helpers/unitUi';

const UC = 'UNITCAMP#pack-3149-fall';
const CAMP = 'CAMP#fall-2026';
const CARAMEL = 'PROD#caramel';
const BUTTER = 'PROD#butter';
const AVERY = 'PROFILE#avery';
const ORDER = 'ORDER#door-1';
const LINE = 'LINE#caramel-1';
const SALE_DATE = '2026-02-06';

const CATALOG_QUERY = {
  request: { query: GET_UNIT_CAMPAIGN_CATALOG, variables: { unitCampaignId: UC } },
  result: {
    data: {
      unitCampaignCatalog: {
        __typename: 'UnitCampaignCatalog',
        catalogId: 'CATALOG#fall',
        catalogName: 'Fall catalog',
        products: [
          { __typename: 'CatalogProduct', productId: CARAMEL, productName: 'Caramel Corn', description: null, price: 6, sortOrder: 1 },
          { __typename: 'CatalogProduct', productId: BUTTER, productName: 'Butter Popcorn', description: null, price: 6, sortOrder: 2 },
        ],
      },
    },
  },
};

const ROSTER_QUERY = {
  request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { unitCampaignId: UC, page: { limit: UNIT_PAGE_SIZE } } },
  result: {
    data: {
      unitCampaignRoster: {
        __typename: 'UnitCampaignMembershipConnection',
        items: [
          {
            __typename: 'UnitCampaignMembership',
            unitCampaignId: UC,
            unitId: 'UNIT#pack-3149',
            campaignId: CAMP,
            profileId: AVERY,
            status: 'ACTIVE',
            joinedByAccountId: 'ACCOUNT#avery',
            joinedAt: '2026-01-20T15:00:00Z',
            removedByAccountId: null,
            removedAt: null,
            version: 1,
            guardVersion: 2,
          },
        ],
        pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
      },
    },
  },
};

/** Caramel, 3 ordered, 1 already consumed from custody: the `SS-SM-04` line. */
function lineFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'LineItem',
    productId: CARAMEL,
    productName: 'Caramel Corn',
    quantity: 3,
    pricePerUnit: 6,
    subtotal: 18,
    lineItemId: LINE,
    fulfilledQuantity: 1,
    ...overrides,
  };
}

function orderFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'Order',
    orderId: ORDER,
    profileId: AVERY,
    campaignId: CAMP,
    customerName: 'Nina Ngo',
    orderDate: '2026-02-06T15:00:00Z',
    paymentMethod: 'Cash',
    totalAmount: 18,
    status: 'NEW',
    createdAt: '2026-02-06T15:00:00Z',
    lineItems: [lineFixture()],
    unitId: 'UNIT#pack-3149',
    unitCampaignId: UC,
    fulfillmentVersion: 3,
    ...overrides,
  };
}

function ordersQuery(orders: unknown[], nextToken: string | null = null, token: string | null = null) {
  return {
    request: { query: LIST_UNIT_SCOUT_ORDERS, variables: { campaignId: CAMP, limit: ORDER_PAGE_SIZE, nextToken: token } },
    result: {
      data: {
        listOrdersByCampaign: {
          __typename: 'OrderConnection',
          orders,
          nextToken,
        },
      },
    },
  };
}

function fulfillmentFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'OrderFulfillment',
    fulfillmentId: 'FUL#custody-1',
    orderId: ORDER,
    campaignId: CAMP,
    profileId: AVERY,
    unitId: 'UNIT#pack-3149',
    unitCampaignId: UC,
    lineItemId: LINE,
    productId: CARAMEL,
    recordType: 'FULFILL',
    quantity: 1,
    source: 'SCOUT_CUSTODY',
    inventoryMovementId: 'MOVE#custody-sale-1',
    reversalOfFulfillmentId: null,
    actorAccountId: 'ACCOUNT#avery',
    createdAt: '2026-02-06T15:10:00Z',
    ...overrides,
  };
}

function participantFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'ParticipantOrderFulfillment',
    fulfillmentId: 'FUL#custody-1',
    lineItemId: LINE,
    productId: CARAMEL,
    recordType: 'FULFILL',
    quantity: 1,
    source: 'SCOUT_CUSTODY',
    reversalOfFulfillmentId: null,
    createdAt: '2026-02-06T15:10:00Z',
    ...overrides,
  };
}

function adminHistoryQuery(records: unknown[], orderId: string = ORDER) {
  return {
    request: { query: GET_ORDER_FULFILLMENTS, variables: { orderId, page: page() } },
    result: {
      data: {
        orderFulfillments: {
          __typename: 'OrderFulfillmentConnection',
          items: records,
          pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
        },
      },
    },
  };
}

function participantHistoryQuery(records: unknown[]) {
  return {
    request: { query: GET_PARTICIPANT_ORDER_FULFILLMENTS, variables: { orderId: ORDER, page: { limit: ORDER_PAGE_SIZE, cursor: null } } },
    result: {
      data: {
        getOrder: {
          __typename: 'Order',
          orderId: ORDER,
          fulfillments: {
            __typename: 'ParticipantOrderFulfillmentConnection',
            items: records,
            pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
          },
        },
      },
    },
  };
}

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

function renderPanel(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      <OrderFulfillmentPanel unitCampaignId={UC} />
    </MockedProvider>,
  );
}

/** Picks the Scout Campaign, which is what starts the Order read. */
async function chooseCampaign(user: ReturnType<typeof userEvent.setup>) {
  await chooseOption('fulfillment-campaign', new RegExp(AVERY), user);
}

/** Chooses the Scout Campaign and waits for its Orders to be on screen. */
async function openOrders(user: ReturnType<typeof userEvent.setup>) {
  await chooseCampaign(user);
  await screen.findByTestId(`order-block-${ORDER}`);
}

/** Opens one line's Fulfill dialog. */
async function openFulfill(user: ReturnType<typeof userEvent.setup>, lineId = LINE) {
  await user.click(screen.getByTestId(`fulfill-${ORDER}-${lineId}`));
  await screen.findByTestId('fulfill-owed-note');
}

/** Opens the Order's fulfillment history. */
async function openHistory(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId(`order-history-${ORDER}`));
  await screen.findByTestId('audit-note');
}

describe('OrderFulfillmentPanel', () => {
  it('shows each line as ordered, fulfilled, and still owed, following the Order cursor to the end', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()], 'PAGE#2'),
      ordersQuery([orderFixture({ orderId: 'ORDER#door-2', lineItems: [lineFixture({ lineItemId: 'LINE#caramel-2', fulfilledQuantity: null })] })], null, 'PAGE#2'),
    ]);

    await openOrders(user);
    expect(await screen.findByTestId(`line-fulfilled-${LINE}`)).toHaveTextContent('1');
    expect(screen.getByTestId(`line-owed-${LINE}`)).toHaveTextContent('2');
    // The second Order only exists past the first page: stopping early would hide a
    // line that still owes two Kernels.
    const second = await screen.findByTestId('order-block-ORDER#door-2');
    expect(within(second).getByTestId('line-owed-LINE#caramel-2')).toHaveTextContent('3');
    expect(within(second).getByTestId('line-fulfilled-LINE#caramel-2')).toHaveTextContent('0');
  });

  it('says there is nothing to fulfill while no Scout Campaign is joined, and offers no sale', async () => {
    renderPanel([
      CATALOG_QUERY,
      {
        request: { query: LIST_UNIT_CAMPAIGN_ROSTER, variables: { unitCampaignId: UC, page: { limit: UNIT_PAGE_SIZE } } },
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

    expect(await screen.findByTestId('no-campaign-note')).toHaveTextContent('No Scout Campaign is joined to this Unit Campaign');
    expect(screen.getByTestId('record-custody-sale')).toBeDisabled();
    expect(screen.getByTestId('no-order-selected-note')).toHaveTextContent('Choose a Scout to see the individual Orders');
  });

  it('SS-SM-04: a door-to-door sale consumes the held stock it can and leaves the rest owed on the line', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([]),
      {
        request: {
          query: RECORD_CUSTODY_SALE,
          variables: {
            input: {
              profileId: AVERY,
              campaignId: CAMP,
              customerName: 'Nina Ngo',
              orderDate: '2026-02-06T00:00:00.000Z',
              paymentMethod: 'Cash',
              lineItems: [{ productId: CARAMEL, quantity: 3 }],
              fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
              // `createOrder` carries its key flat on the input, not in an IdempotencyInput.
              idempotencyKey: 'test-idem-1',
            },
          },
        },
        result: { data: { createOrder: orderFixture() } },
      },
      // One Kernel was consumed from custody and the sale still landed: the other two
      // are owed, and that is the state the screen has to show.
      ordersQuery([orderFixture()]),
    ]);

    await chooseCampaign(user);
    await user.click(screen.getByTestId('record-custody-sale'));
    expect(await screen.findByTestId('sale-mode-note')).toHaveTextContent(`consuming ${AVERY}'s held stock first`);
    await typeInto('sale-customer', 'Nina Ngo', user);
    await clearAndType('sale-date', SALE_DATE, user);
    await typeInto('sale-payment', 'Cash', user);
    await chooseOption('sale-product', 'Caramel Corn', user);
    await clearAndType('sale-quantity', '3', user);
    await user.click(screen.getByTestId('sale-add-line'));
    expect(screen.getByTestId(`sale-line-${CARAMEL}`)).toHaveTextContent('Caramel Corn: 3');
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`line-fulfilled-${LINE}`)).toHaveTextContent('1'));
    expect(screen.getByTestId(`line-owed-${LINE}`)).toHaveTextContent('2');
    expect(screen.getByTestId(`line-owed-${LINE}`)).toHaveTextContent('2');
    await waitFor(() => expect(screen.queryByTestId('form-dialog-confirm')).not.toBeInTheDocument());
  });

  it('refuses a sale it could not write, before sending it', async () => {
    const user = userEvent.setup();
    // No sale mock: nothing in this test may reach the Order API.
    renderPanel([CATALOG_QUERY, ROSTER_QUERY, ordersQuery([])]);

    await chooseCampaign(user);
    await user.click(screen.getByTestId('record-custody-sale'));
    await clearAndType('sale-date', SALE_DATE, user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter the customer name.')).toBeInTheDocument();

    await typeInto('sale-customer', 'Nina Ngo', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter how the customer paid.')).toBeInTheDocument();

    await typeInto('sale-payment', 'Cash', user);
    await clearAndType('sale-date', 'last tuesday', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter the order date as YYYY-MM-DD.')).toBeInTheDocument();

    await clearField('sale-date', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter the order date.')).toBeInTheDocument();

    await clearAndType('sale-date', SALE_DATE, user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Add at least one product line.')).toBeInTheDocument();

    // A line the dialog cannot price is refused where it was typed.
    await clearAndType('sale-quantity', '2.5', user);
    await user.click(screen.getByTestId('sale-add-line'));
    expect(await screen.findByText('Enter a whole number.')).toBeInTheDocument();

    // A quantity with no product to price it for is the other half of the same rule.
    await clearAndType('sale-quantity', '2', user);
    await user.click(screen.getByTestId('sale-add-line'));
    expect(await screen.findByText('Choose a product to add.')).toBeInTheDocument();

    await chooseOption('sale-product', 'Caramel Corn', user);
    await clearAndType('sale-quantity', '0', user);
    await user.click(screen.getByTestId('sale-add-line'));
    expect(await screen.findByText('Enter a quantity above zero.')).toBeInTheDocument();
    expect(screen.queryAllByTestId(/^sale-line-/)).toHaveLength(0);
  });

  it('fulfilling a line names that line and carries the fulfillment version this screen read', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()]),
      {
        request: {
          query: FULFILL_INDIVIDUAL_ORDER_LINE,
          variables: {
            input: {
              orderId: ORDER,
              lineItemId: LINE,
              quantity: 2,
              source: 'KERNEL_STOCK',
              expectedFulfillmentVersion: 3,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            fulfillIndividualOrderLine: {
              __typename: 'FulfillIndividualOrderLinePayload',
              order: orderFixture({ fulfillmentVersion: 4, lineItems: [lineFixture({ fulfilledQuantity: 3 })] }),
              fulfillment: fulfillmentFixture({ fulfillmentId: 'FUL#kernel-1', quantity: 2, source: 'KERNEL_STOCK', inventoryMovementId: 'MOVE#kernel-1' }),
              inventoryPosition: { __typename: 'InventoryPosition', unitCampaignId: UC, productId: CARAMEL },
            },
          },
        },
      },
      ordersQuery([orderFixture({ customerName: 'Reloaded', fulfillmentVersion: 4, lineItems: [lineFixture({ fulfilledQuantity: 3 })] })]),
    ]);

    await openOrders(user);
    await openFulfill(user);
    expect(screen.getByTestId('fulfill-owed-note')).toHaveTextContent('2 of 3 still owed on this line.');
    expect(screen.getByTestId('fulfill-source-note')).toHaveTextContent('Kernel stock moves out of unassigned stock');
    await clearAndType('fulfill-quantity', '2', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`line-fulfilled-${LINE}`)).toHaveTextContent('3'));
    expect(screen.getByTestId(`line-owed-${LINE}`)).toHaveTextContent('0');
    expect(screen.getByTestId(`no-fulfill-${LINE}`)).toHaveTextContent('Nothing owed');
    expect(screen.getByTestId(`order-version-${ORDER}`)).toHaveTextContent('fulfillment record v4');
  });

  it('external-no-balance: a direct Council supply fills the line and says no Kernel stock moved', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()]),
      {
        request: {
          query: FULFILL_INDIVIDUAL_ORDER_LINE,
          variables: {
            input: {
              orderId: ORDER,
              lineItemId: LINE,
              quantity: 1,
              // The Council supply is outside the Kernel's stock, so it moves no
              // Kernel balance and the server needs no custody row to allow it.
              source: 'EXTERNAL_COUNCIL',
              expectedFulfillmentVersion: 3,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            fulfillIndividualOrderLine: {
              __typename: 'FulfillIndividualOrderLinePayload',
              order: orderFixture({ fulfillmentVersion: 4, lineItems: [lineFixture({ fulfilledQuantity: 2 })] }),
              fulfillment: fulfillmentFixture({ fulfillmentId: 'FUL#ext-1', quantity: 1, source: 'EXTERNAL_COUNCIL', inventoryMovementId: null }),
              inventoryPosition: null,
            },
          },
        },
      },
      ordersQuery([orderFixture({ fulfillmentVersion: 4, lineItems: [lineFixture({ fulfilledQuantity: 2 })] })]),
    ]);

    await openOrders(user);
    await openFulfill(user);
    await chooseOption('fulfill-source', fulfillmentSourceLabel('EXTERNAL_COUNCIL'), user);
    // The source decides the stock consequence, and the screen states it before the
    // write is offered.
    expect(await screen.findByTestId('fulfill-source-note')).toHaveTextContent('records no balance movement');
    await clearAndType('fulfill-quantity', '1', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`line-fulfilled-${LINE}`)).toHaveTextContent('2'));
    expect(screen.getByTestId(`line-owed-${LINE}`)).toHaveTextContent('1');
  });

  it('will not fulfill more than the line owes, and will not offer the Scout custody source a second time', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([
        orderFixture(),
        orderFixture({ orderId: 'ORDER#door-2', lineItems: [lineFixture({ productId: BUTTER, lineItemId: 'LINE#butter-1', fulfilledQuantity: 2 })] }),
      ]),
    ]);

    await openOrders(user);
    await openFulfill(user);
    await clearAndType('fulfill-quantity', '3', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Only 2 Kernels are left to fulfill on this line.')).toBeInTheDocument();

    await clearAndType('fulfill-quantity', 'x', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Enter a whole number.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    // The same rule on a line that owes one Kernel, said in the singular.
    await user.click(screen.getByTestId('fulfill-ORDER#door-2-LINE#butter-1'));
    await clearAndType('fulfill-quantity', '2', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));
    expect(await screen.findByText('Only 1 Kernel is left to fulfill on this line.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    // The sale consumed custody already; this dialog can only fill from the Kernel or
    // straight from the Council.
    await openFulfill(user);
    const sourceField = await screen.findByTestId('fulfill-source');
    await user.click(sourceField.querySelector('.MuiSelect-select') as HTMLElement);
    const sources = await screen.findAllByRole('option');
    expect(sources.map((option) => option.textContent)).toEqual(['Kernel stock', 'Direct from Council']);
  });

  it('stale-version: a refused write re-reads the Order, and the next attempt carries the version that read brought back', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()]),
      {
        request: {
          query: FULFILL_INDIVIDUAL_ORDER_LINE,
          variables: {
            input: { orderId: ORDER, lineItemId: LINE, quantity: 2, source: 'KERNEL_STOCK', expectedFulfillmentVersion: 3, idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        error: new GraphQLError('The fulfillment version has moved.', { extensions: { code: 'CONFLICT' } }),
      },
      // Another admin already filled one Kernel: the screen re-reads rather than
      // leaving the button armed with the version that was just refused.
      ordersQuery([orderFixture({ fulfillmentVersion: 4, lineItems: [lineFixture({ fulfilledQuantity: 2 })] })]),
      {
        request: {
          query: FULFILL_INDIVIDUAL_ORDER_LINE,
          variables: {
            input: { orderId: ORDER, lineItemId: LINE, quantity: 1, source: 'KERNEL_STOCK', expectedFulfillmentVersion: 4, idempotency: { idempotencyKey: 'test-idem-2' } },
          },
        },
        result: {
          data: {
            fulfillIndividualOrderLine: {
              __typename: 'FulfillIndividualOrderLinePayload',
              order: orderFixture({ fulfillmentVersion: 5, lineItems: [lineFixture({ fulfilledQuantity: 3 })] }),
              fulfillment: fulfillmentFixture({ fulfillmentId: 'FUL#kernel-2', quantity: 1, source: 'KERNEL_STOCK', inventoryMovementId: 'MOVE#kernel-2' }),
              inventoryPosition: { __typename: 'InventoryPosition', unitCampaignId: UC, productId: CARAMEL },
            },
          },
        },
      },
      ordersQuery([orderFixture({ fulfillmentVersion: 5, lineItems: [lineFixture({ fulfilledQuantity: 3 })] })]),
    ]);

    await openOrders(user);
    expect(await screen.findByTestId(`order-version-${ORDER}`)).toHaveTextContent('fulfillment record v3');
    await openFulfill(user);
    await clearAndType('fulfill-quantity', '2', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    expect(await screen.findByText(/stock or a version has already moved/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(await screen.findByTestId(`order-version-${ORDER}`)).toHaveTextContent('fulfillment record v4');
    expect(screen.getByTestId(`line-owed-${LINE}`)).toHaveTextContent('1');
    await openFulfill(user);
    expect(screen.getByTestId('fulfill-owed-note')).toHaveTextContent('1 of 3 still owed on this line.');
    await clearAndType('fulfill-quantity', '1', user);
    await user.click(screen.getByTestId('form-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId(`line-fulfilled-${LINE}`)).toHaveTextContent('3'));
  });

  it('duplicate-reversal: a fulfillment that already has a reversal offers no second Reverse', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()]),
      adminHistoryQuery([
        fulfillmentFixture(),
        fulfillmentFixture({
          fulfillmentId: 'REV#custody-1',
          recordType: 'REVERSAL',
          quantity: 1,
          source: 'SCOUT_CUSTODY',
          inventoryMovementId: 'MOVE#reversal-1',
          reversalOfFulfillmentId: 'FUL#custody-1',
          createdAt: '2026-02-07T15:00:00Z',
        }),
      ]),
    ]);

    await openOrders(user);
    await openHistory(user);
    expect(await screen.findByTestId('custody-sale-note')).toHaveTextContent("drew on the Scout's held stock first");
    expect(screen.getByTestId('reversal-state-FUL#custody-1')).toHaveTextContent('Already reversed');
    expect(screen.getByTestId('reversal-state-REV#custody-1')).toHaveTextContent('Reversal record');
    expect(screen.queryByTestId('reverse-FUL#custody-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('reverse-REV#custody-1')).not.toBeInTheDocument();
  });

  it('a reversal is a new record linked to the one it undoes, and it carries the version this screen read', async () => {
    const user = userEvent.setup();
    const kernelFulfillment = fulfillmentFixture({
      fulfillmentId: 'FUL#kernel-1',
      quantity: 2,
      source: 'KERNEL_STOCK',
      inventoryMovementId: 'MOVE#kernel-1',
      createdAt: '2026-02-06T16:00:00Z',
    });
    const custodyReversal = fulfillmentFixture({
      fulfillmentId: 'REV#custody-1',
      recordType: 'REVERSAL',
      reversalOfFulfillmentId: 'FUL#custody-1',
      inventoryMovementId: 'MOVE#reversal-1',
      createdAt: '2026-02-07T15:00:00Z',
    });
    const kernelReversal = fulfillmentFixture({
      fulfillmentId: 'REV#kernel-1',
      quantity: 2,
      recordType: 'REVERSAL',
      source: 'KERNEL_STOCK',
      reversalOfFulfillmentId: 'FUL#kernel-1',
      inventoryMovementId: 'MOVE#reversal-2',
      createdAt: '2026-02-07T16:00:00Z',
    });
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()]),
      adminHistoryQuery([fulfillmentFixture(), kernelFulfillment]),
      {
        request: {
          query: REVERSE_INDIVIDUAL_ORDER_FULFILLMENT,
          variables: {
            input: {
              orderId: ORDER,
              fulfillmentId: 'FUL#custody-1',
              expectedFulfillmentVersion: 3,
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            reverseIndividualOrderFulfillment: {
              __typename: 'ReverseIndividualOrderFulfillmentPayload',
              order: orderFixture({ fulfillmentVersion: 4 }),
              reversal: custodyReversal,
              inventoryPosition: null,
            },
          },
        },
      },
      // The history the admin is looking at is the one that has to show the new
      // record, and the fulfillment it is linked to.
      adminHistoryQuery([fulfillmentFixture(), kernelFulfillment, custodyReversal]),
      ordersQuery([orderFixture({ fulfillmentVersion: 4, lineItems: [lineFixture({ fulfilledQuantity: 0 })] })]),
      {
        request: {
          query: REVERSE_INDIVIDUAL_ORDER_FULFILLMENT,
          variables: {
            input: {
              orderId: ORDER,
              fulfillmentId: 'FUL#kernel-1',
              expectedFulfillmentVersion: 3,
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: {
          data: {
            reverseIndividualOrderFulfillment: {
              __typename: 'ReverseIndividualOrderFulfillmentPayload',
              order: orderFixture({ fulfillmentVersion: 4 }),
              reversal: kernelReversal,
              inventoryPosition: { __typename: 'InventoryPosition', unitCampaignId: UC, productId: CARAMEL },
            },
          },
        },
      },
      adminHistoryQuery([fulfillmentFixture(), kernelFulfillment, custodyReversal, kernelReversal]),
      ordersQuery([orderFixture({ fulfillmentVersion: 4, lineItems: [lineFixture({ fulfilledQuantity: 0 })] })]),
    ]);

    await openOrders(user);
    await openHistory(user);
    await user.click(await screen.findByTestId('reverse-FUL#custody-1'));

    const custodyConfirm = screen.getByRole('dialog', { name: 'Reverse this fulfillment' });
    // The copy names the source the stock goes back to, which is the source the
    // fulfillment took — and no other.
    expect(within(custodyConfirm).getByTestId('reversal-copy')).toHaveTextContent(`Reversing returns 1 Kernel to ${fulfillmentSourceLabel('SCOUT_CUSTODY')}`);
    await user.click(within(custodyConfirm).getByRole('button', { name: 'Reverse' }));

    expect(await screen.findByTestId('reversal-state-FUL#custody-1')).toHaveTextContent('Already reversed');
    expect(screen.getByTestId('fulfillment-source-REV#custody-1')).toHaveTextContent("Scout's custody · Kernel stock moved");

    // The Kernel fulfillment reverses back into Kernel stock, in its own words.
    await user.click(await screen.findByTestId('reverse-FUL#kernel-1'));
    const kernelConfirm = screen.getByRole('dialog', { name: 'Reverse this fulfillment' });
    expect(within(kernelConfirm).getByTestId('reversal-copy')).toHaveTextContent('Reversing returns 2 Kernels to Kernel stock');
    await user.click(within(kernelConfirm).getByRole('button', { name: 'Reverse' }));

    await waitFor(() => expect(screen.getByTestId('reversal-state-FUL#kernel-1')).toHaveTextContent('Already reversed'));
  });

  it('privacy: what the Scout sees is the participant projection, with no actor account and no movement', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()]),
      adminHistoryQuery([
        fulfillmentFixture(),
        fulfillmentFixture({
          fulfillmentId: 'FUL#kernel-1',
          quantity: 2,
          source: 'KERNEL_STOCK',
          inventoryMovementId: 'MOVE#kernel-1',
          createdAt: '2026-02-06T16:00:00Z',
        }),
        fulfillmentFixture({
          fulfillmentId: 'REV#custody-1',
          recordType: 'REVERSAL',
          reversalOfFulfillmentId: 'FUL#custody-1',
          inventoryMovementId: 'MOVE#reversal-1',
          createdAt: '2026-02-07T15:00:00Z',
        }),
      ]),
      // The only fulfillment read this block is allowed to make is the participant
      // document, which asks for neither field.
      participantHistoryQuery([
        participantFixture(),
        participantFixture({ fulfillmentId: 'FUL#kernel-1', quantity: 2, source: 'KERNEL_STOCK' }),
        participantFixture({ fulfillmentId: 'REV#custody-1', recordType: 'REVERSAL', reversalOfFulfillmentId: 'FUL#custody-1' }),
      ]),
    ]);

    await openOrders(user);
    await openHistory(user);

    expect(await screen.findByTestId(`fulfillment-actor-${'FUL#custody-1'}`)).toHaveTextContent('ACCOUNT#avery · MOVE#custody-sale-1');

    await user.click(screen.getByTestId('participant-view-toggle'));
    const view = await screen.findByTestId('participant-view');
    expect(within(view).getByTestId('participant-note')).toHaveTextContent('without the admin account or the inventory movement');
    expect(within(view).getByTestId('participant-row-FUL#custody-1')).toHaveTextContent("Fulfilled · Caramel Corn · 1 · Scout's custody");
    expect(within(view).getByTestId('participant-row-FUL#kernel-1')).toHaveTextContent('Fulfilled · Caramel Corn · 2 · Kernel stock');
    // The Scout sees the reversal too — it is her history — and nothing else.
    expect(within(view).getByTestId('participant-row-REV#custody-1')).toHaveTextContent("Reversal · Caramel Corn · 1 · Scout's custody");
    expect(within(view).queryByText(/ACCOUNT#/)).not.toBeInTheDocument();
    expect(within(view).queryByText(/MOVE#/)).not.toBeInTheDocument();
  });

  it('an Order with no records yet says so, and a Council supply records no movement', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([
        orderFixture(),
        orderFixture({ orderId: 'ORDER#legacy-9', lineItems: [lineFixture({ lineItemId: 'LINE#legacy-1' })] }),
      ]),
      adminHistoryQuery([]),
      adminHistoryQuery(
        [
          fulfillmentFixture({
            fulfillmentId: 'FUL#ext-1',
            quantity: 3,
            source: 'EXTERNAL_COUNCIL',
            lineItemId: 'LINE#legacy-1',
            inventoryMovementId: null,
          }),
        ],
        'ORDER#legacy-9',
      ),
      participantHistoryQuery([]),
    ]);

    await openOrders(user);
    await user.click(await screen.findByTestId('order-history-ORDER#door-1'));
    expect(await screen.findByTestId('no-fulfillments-note')).toHaveTextContent('Nothing has been fulfilled on this Order yet.');
    expect(screen.queryByTestId('custody-sale-note')).not.toBeInTheDocument();
    await user.click(screen.getByTestId('participant-view-toggle'));
    expect(await screen.findByTestId('no-participant-fulfillments-note')).toHaveTextContent('No records to show the Scout.');
    await user.click(screen.getByRole('button', { name: 'Done' }));

    await user.click(await screen.findByTestId('order-history-ORDER#legacy-9'));
    // An external Council supply never moved Kernel stock, and the audit says so
    // instead of leaving a movement id out and looking broken.
    expect(await screen.findByTestId('fulfillment-actor-FUL#ext-1')).toHaveTextContent('ACCOUNT#avery · no movement');
    expect(screen.getByTestId('fulfillment-source-FUL#ext-1')).toHaveTextContent('Direct from Council · No Kernel stock changed');
  });

  it("says when the Scout's own view could not be read, instead of showing the Scout no history", async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture()]),
      adminHistoryQuery([fulfillmentFixture()]),
      {
        request: { query: GET_PARTICIPANT_ORDER_FULFILLMENTS, variables: { orderId: ORDER, page: { limit: ORDER_PAGE_SIZE, cursor: null } } },
        error: new GraphQLError('Service unavailable.'),
      },
    ]);

    await openOrders(user);
    await openHistory(user);
    await user.click(screen.getByTestId('participant-view-toggle'));

    expect(await screen.findByText("The Scout's own view of these records could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByTestId('participant-view')).not.toBeInTheDocument();
  });

  it('a version-less Order shows its audit but offers no reversal against nothing', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([orderFixture({ orderId: 'ORDER#legacy-9', fulfillmentVersion: null, lineItems: [lineFixture({ lineItemId: 'LINE#legacy-1' })] })]),
      adminHistoryQuery([fulfillmentFixture({ lineItemId: 'LINE#legacy-1' })], 'ORDER#legacy-9'),
    ]);

    await chooseCampaign(user);
    await screen.findByTestId('order-block-ORDER#legacy-9');
    await user.click(await screen.findByTestId('order-history-ORDER#legacy-9'));
    await screen.findByTestId('audit-note');

    expect(await screen.findByTestId('reversal-state-FUL#custody-1')).toHaveTextContent('This Order carries no fulfillment version');
    expect(screen.queryByTestId('reverse-FUL#custody-1')).not.toBeInTheDocument();
  });

  it('shows a line it cannot act on, and says why in words the admin can act on', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      ordersQuery([
        orderFixture({
          lineItems: [
            lineFixture({ productId: BUTTER, lineItemId: null, fulfilledQuantity: null }),
            lineFixture({ productId: CARAMEL, fulfilledQuantity: 3 }),
          ],
        }),
        orderFixture({ orderId: 'ORDER#legacy-9', fulfillmentVersion: null, lineItems: [lineFixture({ lineItemId: 'LINE#legacy-1' })] }),
      ]),
    ]);

    await openOrders(user);
    expect(await screen.findByTestId('line-row-ORDER#door-1#PROD#butter')).toBeInTheDocument();
    expect(screen.getByTestId('no-fulfill-ORDER#door-1#PROD#butter')).toHaveTextContent('Written before stable line ids, so nothing can name it');
    expect(screen.getByTestId(`no-fulfill-${LINE}`)).toHaveTextContent('Nothing owed');
    expect(screen.getByTestId('order-version-ORDER#legacy-9')).toHaveTextContent('no fulfillment version yet');
    expect(screen.getByTestId('no-fulfill-LINE#legacy-1')).toHaveTextContent('This Order carries no fulfillment version');
  });

  it('an Order list that failed to read is not shown as an empty one', async () => {
    const user = userEvent.setup();
    renderPanel([
      CATALOG_QUERY,
      ROSTER_QUERY,
      {
        request: { query: LIST_UNIT_SCOUT_ORDERS, variables: { campaignId: CAMP, limit: ORDER_PAGE_SIZE, nextToken: null } },
        error: new GraphQLError('Service unavailable.'),
      },
    ]);

    await chooseCampaign(user);
    expect(await screen.findByText("Could not load this Scout's individual Orders.")).toBeInTheDocument();
    expect(screen.queryByTestId('no-orders-note')).not.toBeInTheDocument();
  });

  it('a Scout with no Orders says so, rather than showing an empty table', async () => {
    const user = userEvent.setup();
    renderPanel([CATALOG_QUERY, ROSTER_QUERY, ordersQuery([])]);

    await chooseCampaign(user);
    expect(await screen.findByTestId('no-orders-note')).toHaveTextContent('This Scout has no individual Orders in this campaign.');
  });

  it('an Orders read that lands after the screen has gone writes nothing', async () => {
    const user = userEvent.setup();
    const view = render(
      <MockedProvider
        mocks={
          [
            CATALOG_QUERY,
            ROSTER_QUERY,
            // The read is still in flight when the admin leaves the tab.
            { ...ordersQuery([orderFixture()]), delay: 60 },
          ] as never[]
        }
      >
        <OrderFulfillmentPanel unitCampaignId={UC} />
      </MockedProvider>,
    );

    await chooseCampaign(user);
    view.unmount();
    await new Promise((resolve) => setTimeout(resolve, 120));

    expect(screen.queryByTestId(`order-block-${ORDER}`)).not.toBeInTheDocument();
  });
});
