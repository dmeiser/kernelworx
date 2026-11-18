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
import {
  GET_PARTICIPANT_ORDER_FULFILLMENTS,
  LIST_UNIT_SCOUT_ORDERS,
} from '../src/lib/graphql';
import {
  INVENTORY_PAGE_SIZE,
  MAX_MOVEMENT_RANGE_DAYS,
  MAX_QUANTITY,
  ORDER_PAGE_SIZE,
  canReverse,
  describeInventoryFailure,
  fetchAllCampaignOrders,
  fetchParticipantFulfillments,
  fulfillmentSourceLabel,
  fulfillmentStockNote,
  fulfillmentVersionOf,
  isCustodySale,
  movementDeltas,
  movementTypeLabel,
  page,
  parseDateRange,
  parseQuantity,
  parseReason,
  productLabel,
  reversedFulfillmentIds,
  unfulfilledQuantity,
} from '../src/lib/inventory';

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

const order = (orderId: string) => ({ __typename: 'Order', orderId, lineItems: [] });

describe('fetchAllCampaignOrders', () => {
  it('walks the legacy nextToken pages to the end', async () => {
    const seen: unknown[] = [];
    const client = fakeClient(
      [
        { data: { listOrdersByCampaign: { orders: [order('ORDER#1')], nextToken: 'TOKEN-2' } } },
        { data: { listOrdersByCampaign: { orders: [order('ORDER#2')], nextToken: null } } },
      ],
      seen,
    );

    const orders = await fetchAllCampaignOrders(client, 'CAMPAIGN#devon');
    expect(orders.map((row) => row.orderId)).toEqual(['ORDER#1', 'ORDER#2']);
    const first = seen[0] as { query: unknown; variables: Record<string, unknown>; fetchPolicy: string };
    expect(first.query).toBe(LIST_UNIT_SCOUT_ORDERS);
    expect(first.variables).toEqual({ campaignId: 'CAMPAIGN#devon', limit: ORDER_PAGE_SIZE, nextToken: null });
    const second = seen[1] as { variables: Record<string, unknown> };
    expect(second.variables.nextToken).toBe('TOKEN-2');
    expect(first.fetchPolicy).toBe('network-only');
  });

  it('refuses a list that never ends, rather than returning a prefix', async () => {
    const client = fakeClient([{ data: { listOrdersByCampaign: { orders: [order('ORDER#1')], nextToken: 'SAME' } } }]);
    await expect(fetchAllCampaignOrders(client, 'CAMPAIGN#devon')).rejects.toThrow('did not finish within the page limit');
  });

  it('refuses an answer that carries no Order payload', async () => {
    await expect(fetchAllCampaignOrders(fakeClient([{}]), 'CAMPAIGN#devon')).rejects.toThrow('returned no payload');
  });

  it('carries the server error rather than an empty list', async () => {
    const client = fakeClient([{ error: new Error('offline') }]);
    await expect(fetchAllCampaignOrders(client, 'CAMPAIGN#devon')).rejects.toThrow('offline');
  });
});

const fulfillmentPage = (
  items: { fulfillmentId: string }[],
  pageInfo: { endCursor?: string | null; hasNextPage?: boolean },
) => ({
  getOrder: {
    orderId: 'ORDER#1',
    fulfillments: {
      __typename: 'ParticipantOrderFulfillmentConnection',
      items,
      pageInfo: { __typename: 'PageInfo', ...pageInfo },
    },
  },
});

describe('fetchParticipantFulfillments', () => {
  it('walks the participant connection, which is not a top-level field', async () => {
    const seen: unknown[] = [];
    const client = fakeClient(
      [
        { data: fulfillmentPage([{ fulfillmentId: 'F1' }], { endCursor: 'C2', hasNextPage: true }) },
        { data: fulfillmentPage([{ fulfillmentId: 'F2' }], { endCursor: null, hasNextPage: false }) },
      ],
      seen,
    );

    const rows = await fetchParticipantFulfillments(client, 'ORDER#1');
    expect(rows.map((row) => row.fulfillmentId)).toEqual(['F1', 'F2']);
    const first = seen[0] as { query: unknown; variables: Record<string, unknown> };
    expect(first.query).toBe(GET_PARTICIPANT_ORDER_FULFILLMENTS);
    expect(first.variables).toEqual({ orderId: 'ORDER#1', page: { limit: INVENTORY_PAGE_SIZE, cursor: null } });
  });

  it('refuses a page that claims more and cannot name it', async () => {
    const client = fakeClient([{ data: fulfillmentPage([{ fulfillmentId: 'F1' }], { endCursor: null, hasNextPage: true }) }]);
    await expect(fetchParticipantFulfillments(client, 'ORDER#1')).rejects.toThrow('next page with no cursor');
  });

  it('refuses a cursor that does not move, which would answer forever', async () => {
    const client = fakeClient([
      { data: fulfillmentPage([{ fulfillmentId: 'F1' }], { endCursor: 'C2', hasNextPage: true }) },
      { data: fulfillmentPage([{ fulfillmentId: 'F2' }], { endCursor: 'C2', hasNextPage: true }) },
    ]);
    await expect(fetchParticipantFulfillments(client, 'ORDER#1')).rejects.toThrow('cursor did not advance');
  });

  it('refuses a history that never ends, rather than handing back a prefix', async () => {
    // Every page names a new cursor, so nothing but the page limit can stop this walk.
    let pages = 0;
    const client = {
      query: async () => {
        pages += 1;
        return { data: fulfillmentPage([{ fulfillmentId: `F${pages}` }], { endCursor: `C${pages}`, hasNextPage: true }) };
      },
    } as unknown as ApolloClient;

    await expect(fetchParticipantFulfillments(client, 'ORDER#1')).rejects.toThrow('did not finish within the page limit');
  });

  it('refuses an Order that answered no history at all', async () => {
    await expect(fetchParticipantFulfillments(fakeClient([{ data: {} }]), 'ORDER#1')).rejects.toThrow(
      'answered no fulfillment history',
    );
  });

  it('carries the server error', async () => {
    await expect(fetchParticipantFulfillments(fakeClient([{ error: new Error('gone') }]), 'ORDER#1')).rejects.toThrow('gone');
  });
});
