import { vi, describe, test, expect, beforeEach } from 'vitest';

// Proves both order pipelines compute line items and the total through the ONE
// shared helper, lib/line_items.js (#535). The helper is replaced with a stub
// returning sentinels, so if either resolver ever re-grows its own inline copy
// of the price/total math (or ignores the helper's result) the emitted
// lineItems/totalAmount stop matching the stub and these tests fail.
//
// This is deliberately NOT a source-text assertion: it exercises the real
// resolvers and only the shared module is substituted.

const calls = vi.hoisted(() => [] as Array<{ lineItems: any; catalog: any }>);

vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      autoId: () => 'TESTID',
      time: { nowISO8601: () => '2025-01-01T00:00:00.000Z' },
      dynamodb: { toMapValues: (v: any) => v },
      error: (msg: string, type?: string) => {
        throw new Error(`${type}: ${msg}`);
      }
    }
  };
});

vi.mock(
  '../../tofu/application/appsync/js-resolvers/lib/line_items.js',
  () => ({
    enrichLineItems: (lineItems: any, catalog: any) => {
      calls.push({ lineItems, catalog });
      return {
        enrichedLineItems: [
          {
            productId: 'FROM_SHARED_HELPER',
            productName: 'Stub product',
            quantity: 7,
            pricePerUnit: 1.11,
            subtotal: 7.77
          }
        ],
        totalAmountCents: 777
      };
    }
  })
);

import * as createOrderFn from '../../tofu/application/appsync/js-resolvers/create_order_fn.js';
import * as updateOrderFn from '../../tofu/application/appsync/js-resolvers/update_order_fn.js';

const CATALOG = {
  products: [
    { productId: 'PROD#1', productName: 'Popcorn', price: 9.99 },
    { productId: 'PROD#2', productName: 'Caramel', price: 0.07 }
  ]
};

const LINE_ITEMS = [
  { productId: 'PROD#1', quantity: 2 },
  { productId: 'PROD#2', quantity: 3 }
];

beforeEach(() => {
  calls.length = 0;
});

describe('create_order_fn line-item enrichment', () => {
  test('derives lineItems and totalAmount from the shared helper', () => {
    const ctx: any = {
      args: {
        input: {
          profileId: 'PROFILE#p1',
          campaignId: 'CAMPAIGN#c1',
          customerName: 'Alice',
          orderDate: '2025-01-01T00:00:00.000Z',
          lineItems: LINE_ITEMS
        }
      },
      stash: { campaign: { profileId: 'PROFILE#p1' }, catalog: CATALOG }
    };

    const req: any = createOrderFn.request(ctx);

    expect(calls).toHaveLength(1);
    expect(calls[0].lineItems).toBe(LINE_ITEMS);
    expect(calls[0].catalog).toBe(CATALOG);
    // The order item is the stub's output, not a locally recomputed total.
    expect(req.attributeValues.lineItems).toEqual([
      {
        productId: 'FROM_SHARED_HELPER',
        productName: 'Stub product',
        quantity: 7,
        pricePerUnit: 1.11,
        subtotal: 7.77
      }
    ]);
    expect(req.attributeValues.totalAmount).toBe(7.77);
  });
});

describe('update_order_fn line-item enrichment', () => {
  test('derives lineItems and totalAmount from the shared helper', () => {
    const ctx: any = {
      args: { input: { lineItems: LINE_ITEMS } },
      stash: {
        order: { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o1' },
        catalog: CATALOG
      }
    };

    const req: any = updateOrderFn.request(ctx);

    expect(calls).toHaveLength(1);
    expect(calls[0].lineItems).toBe(LINE_ITEMS);
    expect(calls[0].catalog).toBe(CATALOG);
    expect(req.update.expressionValues[':lineItems']).toEqual([
      {
        productId: 'FROM_SHARED_HELPER',
        productName: 'Stub product',
        quantity: 7,
        pricePerUnit: 1.11,
        subtotal: 7.77
      }
    ]);
    expect(req.update.expressionValues[':totalAmount']).toBe(7.77);
  });
});
