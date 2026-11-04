import { vi, describe, test, expect } from 'vitest';

// ORD-API-01: create_order_fn.js immutably captures the Campaign's joined
// Show & Sell scope (unitId / unitCampaignId) onto each new Order. Independent
// campaigns carry no scope attributes, which AppSync serves as null; removal
// later never rewrites orders created while joined (API-FIX-05).
const errors: Array<{ msg: string; type?: string }> = vi.hoisted(() => []);

vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      autoId: () => 'TESTID',
      time: { nowISO8601: () => '2025-01-01T00:00:00.000Z' },
      dynamodb: { toMapValues: (v: any) => v },
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

function ctxWithCampaign(campaign: any) {
  return {
    args: { input: validInput() },
    stash: {
      catalog: {
        products: [{ productId: 'PRODUCT#1', productName: 'Popcorn', price: 10 }]
      },
      campaign
    }
  };
}

describe('create_order_fn joined-scope capture (ORD-API-01)', () => {
  test('a joined campaign stamps unitId and unitCampaignId onto the order', () => {
    const req: any = createOrderFn.request(
      ctxWithCampaign({
        profileId: 'PROFILE#abc',
        unitId: 'unit-pack-3149-aurora',
        unitCampaignId: 'uc-pack-3149-fall-2026'
      }) as any
    );
    expect(req.attributeValues.unitId).toBe('unit-pack-3149-aurora');
    expect(req.attributeValues.unitCampaignId).toBe('uc-pack-3149-fall-2026');
  });

  test('an independent campaign writes no scope attributes (served as null)', () => {
    const req: any = createOrderFn.request(
      ctxWithCampaign({ profileId: 'PROFILE#abc' }) as any
    );
    expect('unitId' in req.attributeValues).toBe(false);
    expect('unitCampaignId' in req.attributeValues).toBe(false);
  });

  test('a removed-then-retained campaign still stamps the scope it joined with', () => {
    // Removal retains the Campaign link (API-FIX-05): orders created after a
    // removal of MEMBERSHIP (but while the link remains) still capture scope.
    const req: any = createOrderFn.request(
      ctxWithCampaign({
        profileId: 'PROFILE#abc',
        unitId: 'unit-pack-3149-aurora',
        unitCampaignId: 'uc-pack-3149-fall-2026'
      }) as any
    );
    expect(req.operation).toBe('PutItem');
    expect(req.attributeValues.unitCampaignId).toBe('uc-pack-3149-fall-2026');
  });
});
