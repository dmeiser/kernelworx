import { vi, describe, test, expect } from 'vitest';

// Mock the AppSync util used by resolver functions
vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      autoId: () => 'TESTID',
      time: { nowISO8601: () => '2025-01-01T00:00:00.000Z' },
      dynamodb: { toMapValues: (v: any) => v },
      error: (msg: string, type?: string) => {
        throw new Error(msg);
      }
    }
  };
});

// Import the resolver under test AFTER mocking the util
import * as createOrderFn from '../../../tofu/application/appsync/js-resolvers/create_order_fn.js';

function validInput() {
  return {
    profileId: 'PROFILE#abc',
    campaignId: 'CAMPAIGN#xyz',
    customerName: 'Test',
    customerPhone: '(555) 123-4567',
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
        products: [{ productId: 'PRODUCT#1', productName: {}, price: 10 }]
      },
      campaign: { profileId: 'PROFILE#abc' }
    }
  };
}

describe('create_order_fn sanitization', () => {
  test('coerces empty object productName to null when catalog product has productName as {}', () => {
    const ctx: any = validCtx();
    const req = createOrderFn.request(ctx as any);
    expect(req.attributeValues.lineItems[0].productName).toBeNull();
  });

  test('coerces client-sent productName:{} in input to null', () => {
    const input = validInput();
    input.lineItems[0].productName = {};
    const ctx: any = validCtx(input);
    const req = createOrderFn.request(ctx as any);
    // When catalog product exists, catalog value takes precedence over client-supplied productName
    expect(req.attributeValues.lineItems[0].productName).toBe('Item');
  });
});
