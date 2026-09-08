import { vi, describe, test, expect, beforeEach } from 'vitest';

// Guard test for update_order_fn.js: util.error() throws in the AppSync JS
// runtime, but under any mock or changed behavior request() must return
// immediately after util.error() instead of continuing and building an
// UpdateItem from stale or undefined validation results.
const errors: Array<{ msg: string; type?: string }> = vi.hoisted(() => []);

vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      autoId: () => 'TESTID',
      time: { nowISO8601: () => '2025-01-01T00:00:00.000Z' },
      dynamodb: { toMapValues: (v: any) => v },
      // Deliberately does NOT throw: exercises the early-return guards.
      error: (msg: string, type?: string) => {
        errors.push({ msg, type });
      }
    }
  };
});

import * as updateOrderFn from '../../../tofu/application/appsync/js-resolvers/update_order_fn.js';

function validCtx(input?: any) {
  return {
    args: { input: input || {} },
    stash: {
      order: { campaignId: 'CAMPAIGN#xyz', orderId: 'ORDER#1' },
      catalog: {
        products: [{ productId: 'PRODUCT#1', productName: 'Popcorn', price: 10 }]
      }
    }
  };
}

beforeEach(() => {
  errors.length = 0;
});

describe('update_order_fn early-return guards after util.error', () => {
  test('empty customer name records the error and no UpdateItem is built', () => {
    const req: any = updateOrderFn.request(validCtx({ customerName: '  ' }) as any);
    expect(errors).toEqual([{ msg: 'Customer name cannot be empty', type: 'BadRequest' }]);
    // Without the guard, request() would continue and return an UpdateItem
    // whose expression sets the empty customerName.
    expect(req).toBeUndefined();
  });

  test('failed phone validation records the error and no UpdateItem is built', () => {
    const req: any = updateOrderFn.request(validCtx({ customerPhone: '123' }) as any);
    expect(errors).toContainEqual({ msg: 'Phone number must be a valid 10-digit US number', type: 'BadRequest' });
    expect(req).toBeUndefined();
  });

  test('invalid address records the error and no UpdateItem is built', () => {
    const req: any = updateOrderFn.request(validCtx({ customerAddress: { street: '1 Main St' } }) as any);
    expect(errors).toContainEqual({ msg: 'Address is missing required fields: city, state, zipCode', type: 'BadRequest' });
    expect(req).toBeUndefined();
  });

  test('empty order date records the error and no UpdateItem is built', () => {
    const req: any = updateOrderFn.request(validCtx({ orderDate: '' }) as any);
    expect(errors).toEqual([{ msg: 'Order date is required', type: 'BadRequest' }]);
    expect(req).toBeUndefined();
  });

  test('valid input still produces an UpdateItem', () => {
    const req: any = updateOrderFn.request(
      validCtx({ customerName: 'Test', customerPhone: '5551234567', orderDate: '2025-12-31T00:00:00Z' }) as any
    );
    expect(errors).toEqual([]);
    expect(req.operation).toBe('UpdateItem');
  });
});
