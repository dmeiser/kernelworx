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
import * as createPublicOrderFn from '../../../tofu/application/appsync/js-resolvers/create_public_order_fn.js';
import * as baseReadFn from '../../../tofu/application/appsync/js-resolvers/campaign_base_read_for_order_fn.js';

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

  test('the scope is read from the strongly consistent base item, not the GSI locator', () => {
    // The locator (get_campaign_for_order) must query campaignId-index, which
    // cannot serve ConsistentRead; the base read step replaces its stash so a
    // just-committed join's scope is visible (the #438/#545 posture).
    const req: any = baseReadFn.request({
      stash: { campaign: { campaignId: 'CAMPAIGN#xyz', profileId: 'PROFILE#abc' } }
    } as any);
    expect(req.operation).toBe('GetItem');
    expect(req.key).toEqual({ profileId: 'PROFILE#abc', campaignId: 'CAMPAIGN#xyz' });
    expect(req.consistentRead).toBe(true);
  });
});

describe('create_public_order_fn parity (ORD-API-01, public writer)', () => {
  function publicCtxWithCampaign(campaign: any) {
    return {
      stash: {
        catalog: { isDeleted: false, products: [{ productId: 'PRODUCT#1', productName: 'Popcorn', price: 10 }] },
        publicOrder: {
          customerName: 'Test',
          orderDate: '2025-12-31T00:00:00Z',
          paymentMethod: 'CASH',
          lineItems: [{ productId: 'PRODUCT#1', quantity: 1 }]
        },
        profileId: 'PROFILE#abc',
        campaignId: 'CAMPAIGN#xyz',
        sellerName: 'Shop',
        campaign
      }
    } as any;
  }

  test('the public buyer writer stamps the same joined scope from the stashed campaign', () => {
    const req: any = createPublicOrderFn.request(
      publicCtxWithCampaign({
        campaignId: 'CAMPAIGN#xyz',
        unitId: 'unit-pack-3149-aurora',
        unitCampaignId: 'uc-pack-3149-fall-2026'
      })
    );
    expect(req.operation).toBe('TransactWriteItems');
    const putItem = req.transactItems[1];
    expect(putItem.operation).toBe('PutItem');
    expect(putItem.attributeValues.unitId).toBe('unit-pack-3149-aurora');
    expect(putItem.attributeValues.unitCampaignId).toBe('uc-pack-3149-fall-2026');
  });

  test('the public buyer writer stamps nothing for an independent campaign', () => {
    const req: any = createPublicOrderFn.request(
      publicCtxWithCampaign({ campaignId: 'CAMPAIGN#xyz' })
    );
    const putItem = req.transactItems[1];
    expect('unitId' in putItem.attributeValues).toBe(false);
    expect('unitCampaignId' in putItem.attributeValues).toBe(false);
  });
});
