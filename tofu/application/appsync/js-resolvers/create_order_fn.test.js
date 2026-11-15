import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_order_fn.js';
import { parseOrderKey } from './lib/order_keys.js';

describe('create_order_fn request', () => {
  const baseCtx = {
    args: {
      input: {
        profileId: 'PROFILE#p1',
        campaignId: 'CAMPAIGN#c1',
        customerName: 'Alice',
        orderDate: '2024-01-01T00:00:00Z',
        lineItems: [
          { productId: 'PROD#1', quantity: 3 },
        ],
      },
    },
    stash: {
      campaign: { profileId: 'PROFILE#p1' },
      catalog: {
        products: [
          { productId: 'PROD#1', productName: 'Popcorn', price: 1.99 },
          { productId: 'PROD#2', productName: 'Caramel', price: 0.10 },
          { productId: 'PROD#3', productName: 'Cheese', price: 0.20 },
        ],
      },
    },
  };

  it('calculates line item subtotal and totalAmount using integer cents without float drift', () => {
    const result = request(baseCtx);
    assert.strictEqual(result.operation, 'PutItem');
    const order = result.attributeValues;
    assert.strictEqual(order.lineItems[0].subtotal, 5.97);
    assert.strictEqual(order.totalAmount, 5.97);
  });

  it('mints an order id the shared parser reads back as the same campaign (#534)', () => {
    // The minter and the reader now share one grammar owner in
    // lib/order_keys.js, so the key this resolver writes must parse back.
    const result = request(baseCtx);
    assert.deepStrictEqual(parseOrderKey(result.key.orderId), {
      campaignId: 'CAMPAIGN#c1',
      suffix: 'auto-generated-id',
    });
    assert.strictEqual(result.attributeValues.orderId, result.key.orderId);
  });

  it('accurately sums multiple items without float drift (e.g. 0.10 + 0.20 = 0.30)', () => {
    const ctx = {
      ...baseCtx,
      args: {
        input: {
          ...baseCtx.args.input,
          lineItems: [
            { productId: 'PROD#2', quantity: 1 },
            { productId: 'PROD#3', quantity: 1 },
          ],
        },
      },
    };
    const result = request(ctx);
    const order = result.attributeValues;
    assert.strictEqual(order.lineItems[0].subtotal, 0.1);
    assert.strictEqual(order.lineItems[1].subtotal, 0.2);
    assert.strictEqual(order.totalAmount, 0.3);
  });

  it('rejects an empty lineItems array', () => {
    const ctx = {
      ...baseCtx,
      args: {
        input: {
          ...baseCtx.args.input,
          lineItems: [],
        },
      },
    };
    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: Order must have at least one line item/
    );
  });

  it('rejects quantity less than 1', () => {
    const ctx = {
      ...baseCtx,
      args: {
        input: {
          ...baseCtx.args.input,
          lineItems: [{ productId: 'PROD#1', quantity: 0 }],
        },
      },
    };
    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: Quantity must be at least 1/
    );
  });

  it('rejects unknown product in catalog', () => {
    const ctx = {
      ...baseCtx,
      args: {
        input: {
          ...baseCtx.args.input,
          lineItems: [{ productId: 'PROD#UNKNOWN', quantity: 1 }],
        },
      },
    };
    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: Product PROD#UNKNOWN not found in catalog/
    );
  });

  it('stashes the denormalized-totals delta for sync_campaign_totals_fn (#746)', () => {
    const stash = { ...baseCtx.stash };
    request({ ...baseCtx, stash });
    assert.deepStrictEqual(stash.totalsDelta, {
      profileId: 'PROFILE#p1',
      campaignId: 'CAMPAIGN#c1',
      count: 1,
      revenue: 5.97,
    });
  });

  // The joined scope is captured at creation from the membership guard, which is
  // the only read that answers "joined to what, right now". The Campaign row's own
  // pair is a latest-link that removal retains, so it is never the source.
  const JOINED_STASH = {
    membershipGuard: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026', unitId: 'UNIT#pack-3149' },
  };

  // The order row rides either shape: a lone PutItem when there is no guard
  // row to pin, or the PutItem inside a transaction that carries the pin.
  function writtenRow(ctx) {
    const req = request(ctx);
    return req.operation === 'PutItem' ? req.attributeValues : req.transactItems[0].attributeValues;
  }

  it('captures the joined scope on the order row from the join guard (API-FIX-05)', () => {
    const ctx = { ...baseCtx, stash: { ...baseCtx.stash, ...JOINED_STASH } };
    const order = writtenRow(ctx);
    assert.strictEqual(order.unitId, 'UNIT#pack-3149');
    assert.strictEqual(order.unitCampaignId, 'uc-pack-3149-fall-2026');
  });

  it('leaves an order written after removal attributed to no Unit', () => {
    // Removal clears the guard pointer but deliberately keeps the campaign's link
    // so joined history survives. Copying that link would put this sale in a Unit
    // the Scout had already left.
    const ctx = {
      ...baseCtx,
      stash: {
        ...baseCtx.stash,
        campaign: { profileId: 'PROFILE#p1', unitId: 'UNIT#pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' },
      },
    };
    const order = writtenRow(ctx);
    assert.strictEqual(order.unitId, null);
    assert.strictEqual(order.unitCampaignId, null);
  });

  it('attributes an order to the Unit the Scout moved to, not the one the campaign row still shows', () => {
    const ctx = {
      ...baseCtx,
      stash: {
        ...baseCtx.stash,
        campaign: { profileId: 'PROFILE#p1', unitId: 'UNIT#pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' },
        membershipGuard: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-crew-529-spring-2027', unitId: 'UNIT#crew-529' },
      },
    };
    const order = writtenRow(ctx);
    assert.strictEqual(order.unitId, 'UNIT#crew-529');
    assert.strictEqual(order.unitCampaignId, 'uc-crew-529-spring-2027');
  });

  it('names the Unit Campaign a guard points at even when its metadata row is gone', () => {
    const ctx = {
      ...baseCtx,
      stash: {
        ...baseCtx.stash,
        membershipGuard: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026' },
      },
    };
    const order = writtenRow(ctx);
    assert.strictEqual(order.unitCampaignId, 'uc-pack-3149-fall-2026');
    assert.strictEqual(order.unitId, null);
  });

  it('records an independent campaign as a null origin, not an absent field (ORD-API-01-02)', () => {
    // Absent would let a later join look like the order's origin; a recorded null
    // is the fact that this campaign was independent at the moment of sale.
    const order = request(baseCtx).attributeValues;
    assert.strictEqual(order.unitId, null);
    assert.strictEqual(order.unitCampaignId, null);
  });

  it('writes a plain PutItem when no guard row was read', () => {
    // Nothing to pin: an independent campaign has no guard row, and a join that
    // commits afterwards is later than this sale. The PutItem also keeps using
    // the datasource's default table -- no injected table name involved.
    const result = request(baseCtx);
    assert.strictEqual(result.operation, 'PutItem');
    assert.strictEqual(result.table, undefined);
  });

  it('pins the guard in a transaction when a live join was read (FUNC-3)', () => {
    const stash = { ...baseCtx.stash, ...JOINED_STASH };
    const result = request({ ...baseCtx, stash });
    assert.strictEqual(result.operation, 'TransactWriteItems');
    assert.strictEqual(result.transactItems[0].operation, 'PutItem');
    // Real table names, injected by templatefile(); a literal logical name here
    // is what produced AccessDenied on table/Orders in a past deploy.
    assert.strictEqual(result.transactItems[0].table, '${orders_table_name}');
    const pin = result.transactItems[1];
    assert.strictEqual(pin.operation, 'ConditionCheck');
    assert.strictEqual(pin.table, '${unit_campaigns_table_name}');
    assert.deepStrictEqual(pin.key, { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' });
    assert.strictEqual(pin.condition.expression, 'activeUnitCampaignId = :joinedTo');
    assert.deepStrictEqual(pin.condition.expressionValues, { ':joinedTo': 'uc-pack-3149-fall-2026' });
    // A cancelled transaction returns only keys, so the write stashes the row
    // it composed and response() replays it.
    assert.deepStrictEqual(stash.orderItem.orderId, result.transactItems[0].key.orderId);
  });

  it('pins "still no live join" when the guard row exists without one (FUNC-3)', () => {
    // Removal keeps the row and clears the pointer; a rejoin between the read
    // and this commit must fail the pin, not stamp the old removal.
    const ctx = {
      ...baseCtx,
      stash: {
        ...baseCtx.stash,
        membershipGuard: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' },
      },
    };
    const pin = request(ctx).transactItems[1];
    assert.strictEqual(pin.condition.expression, 'attribute_not_exists(activeUnitCampaignId)');
    assert.strictEqual(pin.condition.expressionValues, undefined);
  });
});

describe('create_order_fn response', () => {
  it('returns the order result', () => {
    const order = { orderId: 'ORDER#1', campaignId: 'CAMPAIGN#1' };
    const result = response({ result: order });
    assert.deepStrictEqual(result, order);
  });

  it('replays the stashed row for a transaction write', () => {
    // TransactWriteItems returns only the written keys, so the mutation's
    // Order answer comes from the row request() composed and stashed.
    const order = { orderId: 'ORDER#1', campaignId: 'CAMPAIGN#c1' };
    const result = response({ stash: { orderItem: order }, result: { keys: [{ campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#1' }] } });
    assert.deepStrictEqual(result, order);
  });

  it('maps a transaction cancellation to CONFLICT (FUNC-3: the join moved mid-flight)', () => {
    // The guard pin is the only condition in this transaction, so a
    // cancellation means the stamped scope would not have been current.
    assert.throws(
      () => response({ error: { type: 'DynamoDB:TransactionCanceledException', message: 'Transaction cancelled' } }),
      /CONFLICT: The campaign changed while this order was being placed/
    );
  });

  it('throws on AppSync error', () => {
    assert.throws(
      () => response({ error: { message: 'Failed', type: 'DynamoDB' } }),
      /DynamoDB: Failed/
    );
  });
});
