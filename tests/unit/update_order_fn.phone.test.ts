import { vi, describe, test, expect } from 'vitest';

// Mock the AppSync util used by resolver functions
vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      time: { nowISO8601: () => '2025-01-01T00:00:00.000Z' },
      dynamodb: { toMapValues: (v: any) => v },
      error: (msg: string, type?: string) => {
        throw new Error(msg);
      }
    }
  };
});

// Import the resolver under test AFTER mocking the util
import * as updateOrderFn from '../../tofu/application/appsync/js-resolvers/update_order_fn.js';

function validCtx(input?: any) {
  return {
    args: { input: input || {} },
    stash: {
      order: {
        campaignId: 'CAMPAIGN#xyz',
        orderId: 'ORDER#123'
      }
    }
  };
}

describe('update_order_fn customerPhone handling', () => {
  test('does not touch customerPhone when field is omitted', () => {
    const ctx: any = validCtx({ customerName: 'No Phone Change' });
    const req = updateOrderFn.request(ctx as any);
    expect(req.update.expression).not.toContain('customerPhone = :customerPhone');
    expect(req.update.expressionValues[':customerPhone']).toBeUndefined();
  });

  test('updates customerPhone with a valid number', () => {
    const ctx: any = validCtx({ customerPhone: '(555) 123-4567' });
    const req = updateOrderFn.request(ctx as any);
    expect(req.update.expression).toContain('customerPhone = :customerPhone');
    expect(req.update.expressionValues[':customerPhone']).toBe('+15551234567');
  });

  test('clears customerPhone when null is provided', () => {
    const ctx: any = validCtx({ customerPhone: null });
    const req = updateOrderFn.request(ctx as any);
    expect(req.update.expression).toContain('customerPhone = :customerPhone');
    expect(req.update.expressionValues[':customerPhone']).toBeNull();
  });

  test('clears customerPhone when empty string is provided', () => {
    const ctx: any = validCtx({ customerPhone: '' });
    const req = updateOrderFn.request(ctx as any);
    expect(req.update.expression).toContain('customerPhone = :customerPhone');
    expect(req.update.expressionValues[':customerPhone']).toBeNull();
  });

  test('clears customerPhone when whitespace-only string is provided', () => {
    const ctx: any = validCtx({ customerPhone: '   ' });
    const req = updateOrderFn.request(ctx as any);
    expect(req.update.expression).toContain('customerPhone = :customerPhone');
    expect(req.update.expressionValues[':customerPhone']).toBeNull();
  });

  test('rejects an invalid customerPhone', () => {
    const ctx: any = validCtx({ customerPhone: 'not-a-number' });
    expect(() => updateOrderFn.request(ctx as any)).toThrow(/valid 10-digit US number/i);
  });
});
