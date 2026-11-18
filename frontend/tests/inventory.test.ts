/**
 * The shared rules behind the inventory, custody, and fulfillment screens (§2.6).
 *
 * These are the decisions that must agree with the server: the integer a quantity
 * field will accept, the reason an adjustment cannot be submitted without, the
 * window a movement read may ask for, and what a backend refusal turns into. They
 * live outside the screens so one screen cannot quietly disagree with another.
 *
 * What is deliberately absent: any derived balance. Sellable, assigned, With Scout,
 * and the campaign-wide custody total are the server's, and a browser that added
 * them up itself could state a number the audit trail does not support.
 */

import { describe, expect, it } from 'vitest';
import type { ApolloClient } from '@apollo/client';
import type { GqlInventoryMovementType } from '../src/types/graphql-generated';
import { LIST_UNIT_SCOUT_CAMPAIGN_ORDERS, GET_INVENTORY_POSITIONS } from '../src/lib/graphql';
import {
  INVENTORY_PAGE_SIZE,
  MAX_MOVEMENT_RANGE_DAYS,
  MAX_POSITION_PRODUCT_IDS,
  MAX_QUANTITY,
  canReverse,
  describeInventoryFailure,
  fetchInventoryPositions,
  fetchUnitScoutCampaignOrders,
  fulfillmentSourceLabel,
  fulfillmentStockNote,
  fulfillmentVersionOf,
  isCustodySale,
  movementDeltas,
  movementTypeLabel,
  page,
  participantProjection,
  parseDateRange,
  parseQuantity,
  parseReason,
  positionProductChunks,
  productLabel,
  reversedFulfillmentIds,
  unfulfilledQuantity,
} from '../src/lib/inventory';
import type { GqlOrderFulfillmentFieldsFragment } from '../src/types/graphql-generated';

describe('parseQuantity', () => {
  it('takes the whole positive integer the API expects', () => {
    expect(parseQuantity('4')).toEqual({ value: 4, error: null });
    expect(parseQuantity('  10 ')).toEqual({ value: 10, error: null });
    expect(parseQuantity(String(MAX_QUANTITY))).toEqual({ value: MAX_QUANTITY, error: null });
  });

  it('refuses the shapes the server refuses, in the field’s own words', () => {
    expect(parseQuantity('')).toEqual({ value: null, error: 'Enter a quantity.' });
    expect(parseQuantity('2.5').error).toBe('Enter a whole number.');
    expect(parseQuantity('two').error).toBe('Enter a whole number.');
    expect(parseQuantity('-3').error).toBe('Enter a whole number.');
    expect(parseQuantity('0').error).toBe('Enter a quantity above zero.');
    expect(parseQuantity(String(MAX_QUANTITY + 1)).error).toBe(`Enter a quantity of ${MAX_QUANTITY} or less.`);
  });

  it('lets a signed adjustment go below zero but never stay at zero', () => {
    expect(parseQuantity('-2', { signed: true })).toEqual({ value: -2, error: null });
    expect(parseQuantity('-2.5', { signed: true }).error).toBe('Enter a whole number, positive or negative.');
    expect(parseQuantity('0', { signed: true }).error).toBe('Enter a change other than zero.');
    expect(parseQuantity('-0', { signed: true }).error).toBe('Enter a change other than zero.');
  });

  it('takes zero when the field means it, which is the Council on-order change', () => {
    expect(parseQuantity('0', { signed: true, zeroAllowed: true })).toEqual({ value: 0, error: null });
  });

  it('stops a signed change past the bound the server carries', () => {
    expect(parseQuantity('-1', { signed: true })).toEqual({ value: -1, error: null });
    expect(parseQuantity('-2000000', { signed: true }).error).toBe('Enter a change between -1000000 and 1000000.');
  });
});

describe('parseReason', () => {
  it('requires the reason a stock adjustment cannot be audited without', () => {
    expect(parseReason('')).toBe('Say why the stock changed.');
    expect(parseReason('   ')).toBe('Say why the stock changed.');
    expect(parseReason(' bin miscount ')).toBeNull();
  });

  it('makes the reason optional where it is an expectation, not a movement', () => {
    expect(parseReason('', false)).toBeNull();
  });

  it('states the server’s own length limit', () => {
    expect(parseReason('x'.repeat(501))).toBe('Keep the reason under 500 characters.');
    expect(parseReason('x'.repeat(500))).toBeNull();
  });
});

describe('parseDateRange', () => {
  it('asks for nothing when the admin left the window open', () => {
    expect(parseDateRange('', '')).toEqual({ dateRange: undefined, error: null });
  });

  it('sends one open end as the server-shaped instant', () => {
    expect(parseDateRange('2026-02-01', '')).toEqual({
      dateRange: { startAt: '2026-02-01T00:00:00.000Z' },
      error: null,
    });
    expect(parseDateRange('', '2026-02-09')).toEqual({
      dateRange: { endAt: '2026-02-09T23:59:59.000Z' },
      error: null,
    });
  });

  it('keeps both ends and the order between them', () => {
    const parsed = parseDateRange('2026-02-01', '2026-02-09');
    expect(parsed.error).toBeNull();
    expect(parsed.dateRange).toEqual({
      startAt: '2026-02-01T00:00:00.000Z',
      endAt: '2026-02-09T23:59:59.000Z',
    });
  });

  it('refuses a window the server would not answer', () => {
    expect(parseDateRange('2026-02-09', '2026-02-01').error).toBe('The end date must be after the start date.');
    expect(parseDateRange('2025-01-01', '2026-06-01').error).toBe(
      `The history window can be at most ${MAX_MOVEMENT_RANGE_DAYS} days wide.`,
    );
  });

  it('takes one whole day as a window, from its first minute to its last', () => {
    expect(parseDateRange('2026-02-01', '2026-02-01').error).toBeNull();
  });

  it('refuses a date it cannot place, rather than sending a guess', () => {
    expect(parseDateRange('not-a-date', '').error).toBe('Enter both dates as YYYY-MM-DD.');
    expect(parseDateRange('', '2026-13-45').error).toBe('Enter both dates as YYYY-MM-DD.');
  });
});

describe('describeInventoryFailure', () => {
  it('names the code the operator can act on', () => {
    expect(describeInventoryFailure({ message: 'x' }, 'unused')).toContain('x');
    const asError = (code: string) => ({ message: '', extensions: { code } });
    expect(describeInventoryFailure(asError('CONFLICT'), 'unused')).toContain('already moved');
    expect(describeInventoryFailure(asError('RESOURCE_BUSY'), 'unused')).toContain('nothing was changed');
    expect(describeInventoryFailure(asError('FORBIDDEN'), 'unused')).toContain('Unit Admin');
    expect(describeInventoryFailure(asError('NOT_FOUND'), 'unused')).toContain('not one you can reach');
  });

  it('falls back to the server sentence, then to the screen’s own words', () => {
    expect(describeInventoryFailure({ message: 'Custody would go below zero.' }, 'unused')).toBe(
      'Custody would go below zero.',
    );
    expect(describeInventoryFailure({}, 'Nothing was returned.')).toBe('Nothing was returned.');
  });
});

describe('movement wording', () => {
  it('labels every movement type the filter offers', () => {
    expect(movementTypeLabel('SCOUT_ISSUE')).toBe('Issued to Scout');
    expect(movementTypeLabel('SCOUT_SALE_CONSUME')).toBe('Scout sale consumed custody');
    expect(movementTypeLabel('COUNCIL_ON_ORDER_ADJUST')).toBe('Council on order');
  });

  it('reads back a type it has no wording for as the server wrote it, rather than blanking the row', () => {
    expect(movementTypeLabel('A_TYPE_THE_APP_HAS_NOT_MET_YET' as GqlInventoryMovementType)).toBe('A_TYPE_THE_APP_HAS_NOT_MET_YET');
  });

  it('names only the quantities that actually moved', () => {
    const zero = { kernelPhysicalDelta: 0, soldPossessionDelta: 0, withScoutDelta: 0, assignedDelta: 0, councilOnOrderDelta: 0 };
    expect(movementDeltas(zero)).toBe('—');
    expect(movementDeltas({ ...zero, kernelPhysicalDelta: 14 })).toBe('+14 Kernel');
    expect(movementDeltas({ ...zero, kernelPhysicalDelta: -2, withScoutDelta: 4 })).toBe('-2 Kernel · +4 With Scout');
    expect(movementDeltas({ ...zero, soldPossessionDelta: 1, assignedDelta: -3, councilOnOrderDelta: 8 })).toBe(
      '+1 We Owe held · -3 Assigned · +8 Council on order',
    );
  });

  it('shows a product by name when the catalog is known and by id when it is not', () => {
    const names = new Map([['PROD#caramel', 'Caramel Corn']]);
    expect(productLabel(names, 'PROD#caramel')).toBe('Caramel Corn');
    expect(productLabel(names, 'PROD#gone')).toBe('PROD#gone');
  });
});

describe('page', () => {
  it('asks for the page size every Show & Sell list uses', () => {
    expect(page()).toEqual({ limit: INVENTORY_PAGE_SIZE });
    expect(page(25)).toEqual({ limit: 25 });
  });
});

describe('Order fulfillment rules', () => {
  const line = { quantity: 10, fulfilledQuantity: 4 };

  it('states what a line still owes, never below zero', () => {
    expect(unfulfilledQuantity(line.quantity, line.fulfilledQuantity)).toBe(6);
    expect(unfulfilledQuantity(10, 10)).toBe(0);
    expect(unfulfilledQuantity(10)).toBe(10);
    expect(unfulfilledQuantity(2, 5)).toBe(0);
  });

  it('refuses to name a version for an Order that has none', () => {
    expect(fulfillmentVersionOf({ fulfillmentVersion: 3 })).toBe(3);
    expect(fulfillmentVersionOf({})).toBeNull();
    expect(fulfillmentVersionOf({ fulfillmentVersion: null })).toBeNull();
  });

  it('knows a door-to-door sale by the source it consumed', () => {
    expect(isCustodySale([{ source: 'SCOUT_CUSTODY' } as never])).toBe(true);
    expect(isCustodySale([{ source: 'KERNEL_STOCK' } as never])).toBe(false);
    expect(isCustodySale([])).toBe(false);
  });

  it('offers at most one reversal per fulfillment', () => {
    const records = [
      { fulfillmentId: 'F1', recordType: 'FULFILL', reversalOfFulfillmentId: null },
      { fulfillmentId: 'F2', recordType: 'REVERSAL', reversalOfFulfillmentId: 'F1' },
      { fulfillmentId: 'F3', recordType: 'FULFILL', reversalOfFulfillmentId: null },
    ] as never[];
    const reversed = reversedFulfillmentIds(records);
    expect([...reversed]).toEqual(['F1']);
    expect(canReverse(records[0], reversed)).toBe(false);
    expect(canReverse(records[2], reversed)).toBe(true);
    // A reversal record is never itself reversible.
    expect(canReverse(records[1], reversed)).toBe(false);
  });

  it('says which stock a record moved, because an external supply moved none', () => {
    expect(fulfillmentSourceLabel('EXTERNAL_COUNCIL')).toBe('Direct from Council');
    expect(fulfillmentSourceLabel('SCOUT_CUSTODY')).toBe("Scout's custody");
    expect(fulfillmentSourceLabel('MYSTERY')).toBe('MYSTERY');
    expect(fulfillmentStockNote({ source: 'EXTERNAL_COUNCIL' } as never)).toBe('No Kernel stock changed');
    expect(fulfillmentStockNote({ source: 'KERNEL_STOCK' } as never)).toBe('Kernel stock moved');
  });
});

/** A client that answers with the pages a test names, in order. */
function fakeClient(pages: { data?: unknown; error?: unknown }[], seen: unknown[] = []): ApolloClient {
  let index = 0;
  return {
    query: async (request: unknown) => {
      seen.push(request);
      const next = pages[Math.min(index, pages.length - 1)];
      index += 1;
      return next;
    },
  } as unknown as ApolloClient;
}

const UNIT_CAMPAIGN = 'UNITCAMP#pack-3149-fall';

const order = (orderId: string) => ({ __typename: 'UnitOrder', orderId, lineItems: [] });

const orderPage = (
  items: { orderId: string }[],
  pageInfo: { endCursor?: string | null; hasNextPage?: boolean },
) => ({
  unitScoutCampaignOrders: {
    __typename: 'UnitOrderConnection',
    items,
    pageInfo: { __typename: 'PageInfo', ...pageInfo },
  },
});

describe('fetchUnitScoutCampaignOrders', () => {
  it('walks the Unit-Admin Order pages to the end', async () => {
    const seen: unknown[] = [];
    const client = fakeClient(
      [
        { data: orderPage([order('ORDER#1')], { endCursor: 'C2', hasNextPage: true }) },
        { data: orderPage([order('ORDER#2')], { endCursor: null, hasNextPage: false }) },
      ],
      seen,
    );

    const orders = await fetchUnitScoutCampaignOrders(client, UNIT_CAMPAIGN, 'CAMPAIGN#devon');

    expect(orders.map((row) => row.orderId)).toEqual(['ORDER#1', 'ORDER#2']);
    const first = seen[0] as { query: unknown; variables: Record<string, unknown>; fetchPolicy: string };
    // The read names the Unit Campaign whose admin is asking. That scope, not a Profile
    // ownership check or a READ share, is what authorizes it: the admin who owes the stock
    // these Orders sold holds neither (§2.6.3).
    expect(first.query).toBe(LIST_UNIT_SCOUT_CAMPAIGN_ORDERS);
    expect(first.variables).toEqual({
      unitCampaignId: UNIT_CAMPAIGN,
      campaignId: 'CAMPAIGN#devon',
      page: { limit: INVENTORY_PAGE_SIZE },
    });
    expect((seen[1] as { variables: Record<string, unknown> }).variables.page).toEqual({
      limit: INVENTORY_PAGE_SIZE,
      cursor: 'C2',
    });
    expect(first.fetchPolicy).toBe('network-only');
  });

  it('refuses a list that never ends, rather than returning a prefix', async () => {
    // Every page names a new cursor, so nothing but the page limit can stop this walk —
    // and a prefix of the Order list would read as the whole of it.
    let pages = 0;
    const client = {
      query: async () => {
        pages += 1;
        return { data: orderPage([order(`ORDER#${pages}`)], { endCursor: `C${pages}`, hasNextPage: true }) };
      },
    } as unknown as ApolloClient;

    await expect(fetchUnitScoutCampaignOrders(client, UNIT_CAMPAIGN, 'CAMPAIGN#devon')).rejects.toThrow(
      'did not finish within the page limit',
    );
  });

  it('refuses a page that claims more and cannot name the cursor', async () => {
    const client = fakeClient([{ data: orderPage([order('ORDER#1')], { hasNextPage: true }) }]);
    await expect(fetchUnitScoutCampaignOrders(client, UNIT_CAMPAIGN, 'CAMPAIGN#devon')).rejects.toThrow(
      'next page with no cursor',
    );
  });

  it('refuses an answer that carries no Order payload', async () => {
    await expect(fetchUnitScoutCampaignOrders(fakeClient([{}]), UNIT_CAMPAIGN, 'CAMPAIGN#devon')).rejects.toThrow(
      'answered no payload',
    );
  });

  it('carries the server error rather than an empty list', async () => {
    const client = fakeClient([{ error: new Error('offline') }]);
    await expect(fetchUnitScoutCampaignOrders(client, UNIT_CAMPAIGN, 'CAMPAIGN#devon')).rejects.toThrow('offline');
  });
});

describe('participantProjection', () => {
  const record = {
    __typename: 'OrderFulfillment',
    fulfillmentId: 'FUL#custody-1',
    orderId: 'ORDER#1',
    campaignId: 'CAMP#devon',
    profileId: 'PROFILE#devon',
    unitId: 'UNIT#pack-3149',
    unitCampaignId: UNIT_CAMPAIGN,
    lineItemId: 'LINE#1',
    productId: 'PROD#caramel',
    recordType: 'FULFILL',
    quantity: 1,
    source: 'SCOUT_CUSTODY',
    inventoryMovementId: 'MOVE#custody-sale-1',
    reversalOfFulfillmentId: null,
    actorAccountId: 'ACCOUNT#avery',
    createdAt: '2026-02-06T15:10:00Z',
  } as unknown as GqlOrderFulfillmentFieldsFragment;

  it('keeps the history a Scout owns and drops both administrative fields', () => {
    const [row] = participantProjection([record]);

    expect(row.fulfillmentId).toBe('FUL#custody-1');
    expect(row.quantity).toBe(1);
    expect(row.source).toBe('SCOUT_CUSTODY');
    expect(row.createdAt).toBe('2026-02-06T15:10:00Z');
    expect('actorAccountId' in row).toBe(false);
    expect('inventoryMovementId' in row).toBe(false);
  });

  it('cannot name who acted or which movement moved stock, on any record', () => {
    const rows = participantProjection([record, { ...record, fulfillmentId: 'REV#1', recordType: 'REVERSAL' }]);

    // The keys are gone from the objects, so no rendering choice on the screen can put
    // them back: the preview of the Scout's view is built by subtraction, the same rule
    // the server applies to Order.fulfillments (§10.2).
    expect(rows.map((row) => Object.keys(row))).toEqual([
      [
        '__typename',
        'fulfillmentId',
        'orderId',
        'campaignId',
        'profileId',
        'unitId',
        'unitCampaignId',
        'lineItemId',
        'productId',
        'recordType',
        'quantity',
        'source',
        'reversalOfFulfillmentId',
        'createdAt',
      ],
      [
        '__typename',
        'fulfillmentId',
        'orderId',
        'campaignId',
        'profileId',
        'unitId',
        'unitCampaignId',
        'lineItemId',
        'productId',
        'recordType',
        'quantity',
        'source',
        'reversalOfFulfillmentId',
        'createdAt',
      ],
    ]);
  });
});

const position = (productId: string) => ({ __typename: 'InventoryPosition', productId, unitCampaignId: UNIT_CAMPAIGN });

describe('the position board reads every catalog product', () => {
  it('splits a catalog into the sets one read may name', () => {
    const ids = Array.from({ length: MAX_POSITION_PRODUCT_IDS * 2 + 3 }, (_, index) => `PROD#${index}`);

    const chunks = positionProductChunks(ids);

    expect(chunks.map((chunk) => chunk.length)).toEqual([
      MAX_POSITION_PRODUCT_IDS,
      MAX_POSITION_PRODUCT_IDS,
      3,
    ]);
    expect(chunks.flat()).toEqual(ids);
    expect(positionProductChunks([])).toEqual([]);
  });

  it('names every product, and keeps the zero the server answers for a product never received', async () => {
    const seen: unknown[] = [];
    const ids = Array.from({ length: MAX_POSITION_PRODUCT_IDS + 2 }, (_, index) => `PROD#${index}`);
    // The untouched product is answered with zeros only because the read named it, which
    // is what lets an admin receive for it from the board.
    const zeros = { ...position('PROD#3'), kernelPhysicalQty: 0, unassignedKernelQty: 0, assignedOpenQty: 0, withScoutQty: 0 };
    const client = fakeClient(
      [
        {
          data: {
            inventoryPositions: {
              __typename: 'InventoryPositionConnection',
              items: [position('PROD#0'), zeros],
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
        {
          data: {
            inventoryPositions: {
              __typename: 'InventoryPositionConnection',
              items: [position('PROD#15'), position('PROD#16')],
              pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
            },
          },
        },
      ],
      seen,
    );

    const rows = await fetchInventoryPositions(client, UNIT_CAMPAIGN, ids);

    expect(rows.map((row) => row.productId)).toEqual(['PROD#0', 'PROD#3', 'PROD#15', 'PROD#16']);
    expect(rows[1].kernelPhysicalQty).toBe(0);
    const variables = (seen as { variables: Record<string, unknown> }[]).map((call) => call.variables);
    expect(variables[0].productIds).toEqual(ids.slice(0, MAX_POSITION_PRODUCT_IDS));
    expect(variables[1].productIds).toEqual(ids.slice(MAX_POSITION_PRODUCT_IDS));
    expect((seen[0] as { query: unknown }).query).toBe(GET_INVENTORY_POSITIONS);
  });
});
