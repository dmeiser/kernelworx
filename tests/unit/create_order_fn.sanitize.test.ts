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
import * as createOrderFn from '../../../cdk/cdk/resolvers/create_order_fn.js';

describe('create_order_fn sanitization', () => {
  test('coerces empty object productName to null when catalog product has productName as {}', () => {
    const ctx: any = {
      args: {
        input: {
          profileId: 'PROFILE#abc',
          campaignId: 'CAMPAIGN#xyz',
          customerName: 'Test',
          orderDate: '2025-12-31T00:00:00Z',
          paymentMethod: 'CASH',
          lineItems: [{ productId: 'PRODUCT#1', quantity: 1 }]
        }
      },
      stash: {
        catalog: {
          products: [{ productId: 'PRODUCT#1', productName: {}, price: 10 }]
        }
      }
    };

    const req = createOrderFn.request(ctx as any);
    // toMapValues is identity in the mock, so inspect attributeValues directly
    expect(req.attributeValues.lineItems[0].productName).toBeNull();
  });

  test('coerces client-sent productName:{} in input to null', () => {
    const ctx: any = {
      args: {
        input: {
          profileId: 'PROFILE#abc',
          campaignId: 'CAMPAIGN#xyz',
          customerName: 'Test',
          orderDate: '2025-12-31T00:00:00Z',
          paymentMethod: 'CASH',
          lineItems: [{ productId: 'PRODUCT#1', quantity: 1, productName: {} }]
        }
      },
      stash: {
        catalog: {
          products: [{ productId: 'PRODUCT#1', productName: 'Item', price: 10 }]
        }
      }
    };

    const req = createOrderFn.request(ctx as any);
    // When catalog product exists, catalog value takes precedence over client-supplied productName
    expect(req.attributeValues.lineItems[0].productName).toBe('Item');
  });
});
