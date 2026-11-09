// Golden oracles for the createOrder NONE path (Show & Sell wave 3, phase A).
//
// These tests pin the EXISTING behavior of the JS createOrder pipeline's
// final write step before the custody wave adds a Lambda delegation step to
// that pipeline. A golden oracle is a contract the custody redesign must not
// break: NONE mode keeps behaving exactly as pinned here, and the custody
// Lambda (separate Python pin: schema-derived committed-replay cases +
// corruption-direction probes) must satisfy the same oracle classes.
//
// Oracle classes pinned:
//   O1  partial-write containment — NONE mode issues ONE PutItem; it never
//       touches inventory/fulfillment tables (the custody class is the
//       addition, not a rewrite of NONE).
//   O2  money integrity — integer-cents math, no float drift.
//   O3  key grammar — the order id the minter writes parses back through the
//       shared parser and equals the PutItem key.
//   O4  totals delta — the denormalized counter stash is exact (a missing or
//       doubled delta corrupts campaign summaries downstream).
//   O5  deterministic validation — the error-code surface for bad input.
//   O6  spec-input tolerance — the spec's createOrder fields that do not
//       apply to NONE (fulfillmentMode explicitly NONE, idempotencyKey
//       present) must not change NONE behavior today; they are the custody
//       wave's extension points.
import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_order_fn.js';
import { parseOrderKey } from './lib/order_keys.js';

const catalog = {
  products: [
    { productId: 'PROD#1', productName: 'Popcorn', price: 1.99 },
    { productId: 'PROD#2', productName: 'Caramel', price: 0.1 },
    { productId: 'PROD#3', productName: 'Cheese', price: 0.2 },
    { productId: 'PROD#4', productName: 'Free Sticker', price: 0 },
  ],
};

function ctxWith(overrides = {}, stashOverrides = {}) {
  return {
    args: {
      input: {
        profileId: 'PROFILE#p1',
        campaignId: 'CAMPAIGN#c1',
        customerName: 'Alice',
        orderDate: '2024-01-01T00:00:00Z',
        paymentMethod: 'CASH',
        lineItems: [{ productId: 'PROD#1', quantity: 3 }],
        ...overrides,
      },
    },
    stash: {
      campaign: { profileId: 'PROFILE#p1' },
      catalog,
      ...stashOverrides,
    },
  };
}

describe('golden oracle O1: NONE-mode partial-write containment', () => {
  it('issues exactly one PutItem keyed {campaignId, orderId} — no cross-table writes', () => {
    const result = request(ctxWith());
    assert.strictEqual(result.operation, 'PutItem');
    assert.deepStrictEqual(Object.keys(result.key).sort(), ['campaignId', 'orderId']);
    // The item must not carry inventory/fulfillment fields in NONE mode: a
    // NONE order has no custody footprint to leave behind.
    const item = result.attributeValues;
    assert.ok(!('fulfillmentMode' in item) || item.fulfillmentMode === undefined);
    assert.ok(!('origin' in item) || item.origin === undefined);
  });

  it('response passes the stored order through and surfaces pipeline errors', () => {
    const order = { orderId: 'ORDER#x' };
    assert.deepStrictEqual(response({ result: order }), order);
    assert.throws(
      () => response({ error: { message: 'boom', type: 'Conflict' } }),
      /Conflict: boom/
    );
  });
});

describe('golden oracle O2: money integrity (integer cents)', () => {
  it('0.10 + 0.20 sums to exactly 0.30', () => {
    const result = request(
      ctxWith({ lineItems: [{ productId: 'PROD#2', quantity: 1 }, { productId: 'PROD#3', quantity: 1 }] })
    );
    assert.strictEqual(result.attributeValues.totalAmount, 0.3);
  });

  it('3 x 1.99 = 5.97 exactly, per-line and total', () => {
    const result = request(ctxWith());
    const order = result.attributeValues;
    assert.strictEqual(order.lineItems[0].pricePerUnit, 1.99);
    assert.strictEqual(order.lineItems[0].subtotal, 5.97);
    assert.strictEqual(order.totalAmount, 5.97);
  });

  it('a zero-price product contributes exactly 0', () => {
    const result = request(ctxWith({ lineItems: [{ productId: 'PROD#4', quantity: 2 }] }));
    assert.strictEqual(result.attributeValues.totalAmount, 0);
  });
});

describe('golden oracle O3: order-key grammar', () => {
  it('the written key parses back to the same campaign and equals the item id', () => {
    const result = request(ctxWith());
    assert.deepStrictEqual(parseOrderKey(result.key.orderId), {
      campaignId: 'CAMPAIGN#c1',
      suffix: 'auto-generated-id',
    });
    assert.strictEqual(result.attributeValues.orderId, result.key.orderId);
  });
});

describe('golden oracle O4: campaign-totals delta stash', () => {
  it('carries exactly {profileId, campaignId, count: 1, revenue: totalAmount}', () => {
    const ctx = ctxWith();
    const result = request(ctx);
    assert.deepStrictEqual(ctx.stash.totalsDelta, {
      profileId: 'PROFILE#p1',
      campaignId: 'CAMPAIGN#c1',
      count: 1,
      revenue: result.attributeValues.totalAmount,
    });
  });
});

describe('golden oracle O5: deterministic validation surface', () => {
  it('rejects a campaign from a different profile with UNAUTHORIZED', () => {
    const ctx = ctxWith({}, { campaign: { profileId: 'PROFILE#other' } });
    assert.throws(() => request(ctx), /UNAUTHORIZED: Campaign does not belong to the specified profile/);
  });

  it('rejects a missing catalog', () => {
    const ctx = ctxWith({}, { catalog: null });
    assert.throws(() => request(ctx), /INVALID_INPUT: Catalog could not be loaded for this campaign/);
  });

  it('rejects an unknown product', () => {
    const ctx = ctxWith({ lineItems: [{ productId: 'PROD#NOPE', quantity: 1 }] });
    assert.throws(() => request(ctx), /INVALID_INPUT: Product PROD#NOPE not found in catalog/);
  });
});

describe('golden oracle O6: spec-input tolerance on the NONE path', () => {
  it('explicit fulfillmentMode NONE behaves identically to its absence', () => {
    const baseline = request(ctxWith());
    const explicit = request(ctxWith({ fulfillmentMode: 'NONE' }));
    // Identical modulo the (mocked-fixed) id and timestamp: compare the
    // written shapes, not the generated values.
    const strip = (r) => {
      const item = { ...r.attributeValues };
      delete item.orderId;
      delete item.createdAt;
      delete item.updatedAt;
      return { keyCampaign: r.key.campaignId, item };
    };
    assert.deepStrictEqual(strip(explicit), strip(baseline));
  });

  it('a present idempotencyKey is tolerated (ignored) on the NONE path today', () => {
    const result = request(ctxWith({ idempotencyKey: 'golden-key-0001' }));
    assert.strictEqual(result.operation, 'PutItem');
  });
});
