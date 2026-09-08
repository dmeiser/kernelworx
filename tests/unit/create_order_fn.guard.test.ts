import { vi, describe, test, expect, beforeEach } from 'vitest';

// Guard test for create_order_fn.js: util.error() throws in the AppSync JS
// runtime, but under any mock or changed behavior the validation helpers must
// return immediately after util.error() instead of continuing with stale or
// undefined variables.
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

import * as createOrderFn from '../../../tofu/application/appsync/js-resolvers/create_order_fn.js';

function validInput() {
  return {
    profileId: 'PROFILE#abc',
    campaignId: 'CAMPAIGN#xyz',
    customerName: 'Test',
    customerPhone: '5551234567',
    orderDate: '2025-12-31T00:00:00Z',
    paymentMethod: 'CASH',
    lineItems: [{ productId: 'PRODUCT#1', quantity: 1 }]
  };
}

function validCtx(input?: any) {
  return {
    args: { input: input || validInput() },
    stash: {
      catalog: {
        products: [{ productId: 'PRODUCT#1', productName: 'Popcorn', price: 10 }]
      },
      campaign: { profileId: 'PROFILE#abc' }
    }
  };
}

beforeEach(() => {
  errors.length = 0;
});

describe('create_order_fn early-return guards after util.error', () => {
  test('missing customer name records the error and validation stops immediately', () => {
    const input = validInput();
    input.customerName = '';
    // Invalid phone too: if validateCustomer continued past the name check,
    // the phone error would be recorded as well.
    input.customerPhone = '123';
    const req: any = createOrderFn.request(validCtx(input) as any);
    expect(errors).toEqual([{ msg: 'Customer name is required', type: 'BadRequest' }]);
    expect(req.operation).toBe('PutItem');
  });

  test('failed phone validation records the error without leaking a stale value', () => {
    const input = validInput();
    input.customerPhone = '123';
    const req: any = createOrderFn.request(validCtx(input) as any);
    expect(errors).toContainEqual({ msg: 'Phone number must be a valid 10-digit US number', type: 'BadRequest' });
    // The guard keeps customerPhone unset instead of copying phoneResult.value.
    expect(req.attributeValues.customerPhone).toBeUndefined();
  });

  test('invalid address records the error without crashing the request', () => {
    const input = validInput();
    input.customerAddress = { street: '1 Main St' };
    const req: any = createOrderFn.request(validCtx(input) as any);
    expect(errors).toContainEqual({ msg: 'Address is missing required fields: city, state, zipCode', type: 'BadRequest' });
    expect(req.operation).toBe('PutItem');
  });

  test('missing order date records the error without crashing the request', () => {
    const input = validInput();
    input.orderDate = '';
    const req: any = createOrderFn.request(validCtx(input) as any);
    expect(errors).toEqual([{ msg: 'Order date is required', type: 'BadRequest' }]);
    expect(req.operation).toBe('PutItem');
  });
});
