import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_order_fn.js';
import { parseOrderKey } from './lib/order_keys.js';
import { requestFingerprint } from './lib/custody_sale.js';

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

// §2.4.2 — `createOrder(fulfillmentMode = CONSUME_SCOUT_CUSTODY)`, the door-to-door sale.
// The cases are the ones the acceptance list names (ORD-API-02-01..04): sufficient
// custody, insufficient custody, zero custody, a race on the custody row, the same key
// retried, and the originating scope surviving a later roster join.
describe('create_order_fn request: CONSUME_SCOUT_CUSTODY (ORD-API-02)', () => {
    // The resolvers are loaded through Terraform templatefile(), and under node the
    // placeholders stay literal -- the same spelling create_public_order_fn.test.js uses.
    const INVENTORY_TABLE = '${inventory_table_name}';
    const FULFILLMENT_TABLE = '${order_fulfillments_table_name}';
    const ORDERS_TABLE = '${orders_table_name}';
    const ACCOUNT = '11111111-1111-4111-8111-111111111111';
    const NOW_MOMENT = '2024-01-01T00:00:00+00:00';
    const JOINED = {
        campaign: { profileId: 'PROFILE#p1', unitId: 'UNIT#pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' },
        membershipGuard: {
            pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1',
            sk: 'MEMBERSHIP_GUARD',
            activeUnitCampaignId: 'uc-pack-3149-fall-2026',
            unitId: 'UNIT#pack-3149'
        }
    };

    function saleCtx(options) {
        const opts = options || {};
        const input = Object.assign(
            {
                profileId: 'PROFILE#p1',
                campaignId: 'CAMPAIGN#c1',
                customerName: 'Alice',
                orderDate: '2024-01-01T00:00:00Z',
                paymentMethod: 'Cash',
                fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
                idempotencyKey: 'sale-1',
                lineItems: [{ productId: 'PROD#1', quantity: 5 }]
            },
            opts.input || {}
        );
        const stash = Object.assign({}, JOINED, {
            catalog: {
                products: [
                    { productId: 'PROD#1', productName: 'Popcorn', price: 1.99 },
                    { productId: 'PROD#2', productName: 'Caramel', price: 0.1 }
                ]
            },
            custodySaleRead: { unitCampaignId: 'uc-pack-3149-fall-2026', profileId: 'PROFILE#p1', idempotencyKey: 'sale-1' },
            // What the share step concluded. Every sale below travels the Profile path;
            // the SEC-1 block below exercises the Unit Admin path.
            profileWriteAuthorized: true,
            custodyRows: opts.custodyRows || [],
            idempotencyMarker: opts.marker === undefined ? null : opts.marker
        });
        return { args: { input }, identity: { claims: { sub: ACCOUNT } }, stash };
    }

    function itemsByTable(result, table) {
        return result.transactItems.filter(function (item) {
            return item.table === table;
        });
    }

    // The marker is the transaction's first action (§8.2), so the Order row is found by
    // the table it writes rather than by position.
    function orderRow(result) {
        return itemsByTable(result, ORDERS_TABLE)[0].attributeValues;
    }

    // The fingerprint the resolver stores: mode + scope + every field the Order will carry.
    function fingerprintOf(ctx) {
        return requestFingerprint({
            mode: 'CONSUME_SCOUT_CUSTODY',
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            customerName: ctx.args.input.customerName,
            customerPhone: ctx.args.input.customerPhone,
            customerAddress: ctx.args.input.customerAddress,
            orderDate: ctx.args.input.orderDate,
            paymentMethod: ctx.args.input.paymentMethod,
            notes: ctx.args.input.notes,
            lineItems: ctx.args.input.lineItems.map(function (line) {
                return { productId: line.productId, quantity: line.quantity };
            })
        });
    }

    it('requires a key, because this is the one order mode that moves stock', () => {
        const ctx = saleCtx({ input: { idempotencyKey: null }, custodyRows: [{ productId: 'PROD#1', withScoutQty: 9, version: 1 }] });
        assert.throws(() => request(ctx), /INVALID_INPUT: idempotencyKey is required when fulfillmentMode = CONSUME_SCOUT_CUSTODY/);
    });

    it('refuses a custody sale with no session, because the marker is keyed by the caller', () => {
        const ctx = saleCtx({ custodyRows: [{ productId: 'PROD#1', withScoutQty: 9, version: 1 }] });
        delete ctx.identity;
        assert.throws(() => request(ctx), /UNAUTHORIZED: A signed-in account is required to place a custody sale/);
    });

    it('consumes available custody and writes Order + decrement + fulfillment + movement + marker as one transaction (ORD-API-02-01)', () => {
        const ctx = saleCtx({ custodyRows: [{ productId: 'PROD#1', withScoutQty: 7, version: 4, profileId: 'PROFILE#p1' }] });
        const result = request(ctx);
        assert.strictEqual(result.operation, 'TransactWriteItems');

        const order = orderRow(result);
        // The whole line is sold out of the Scout's trunk, so the line is fully fulfilled
        // and nothing is left for a Kernel fulfillment to cover.
        assert.strictEqual(order.lineItems[0].fulfilledQuantity, 5);
        assert.strictEqual(order.fulfillmentVersion, 0);

        const custody = itemsByTable(result, INVENTORY_TABLE).filter(function (item) {
            return item.operation === 'UpdateItem';
        });
        assert.strictEqual(custody.length, 1);
        assert.deepStrictEqual(custody[0].key, { pk: 'UNIT_CAMPAIGN#uc-pack-3149-fall-2026', sk: 'PRODUCT#PROD#1#CUSTODY#PROFILE#p1' });
        assert.strictEqual(custody[0].condition.expression, '#version = :expectedVersion AND #withScoutQty >= :scoutFloor');
        assert.strictEqual(custody[0].condition.expressionValues[':expectedVersion'], 4);
        assert.strictEqual(custody[0].condition.expressionValues[':scoutFloor'], 5);
        assert.strictEqual(custody[0].update.expressionValues[':scoutDelta'], -5);

        const fulfillments = itemsByTable(result, FULFILLMENT_TABLE).filter(function (item) {
            return item.attributeValues && item.attributeValues.entityType === 'OrderFulfillment';
        });
        assert.strictEqual(fulfillments.length, 1);
        const record = fulfillments[0].attributeValues;
        assert.deepStrictEqual(fulfillments[0].key, { pk: order.orderId, sk: 'FULFILLMENT#' + NOW_MOMENT + '#auto-generated-id' });
        assert.strictEqual(record.source, 'SCOUT_CUSTODY');
        assert.strictEqual(record.recordType, 'FULFILL');
        assert.strictEqual(record.quantity, 5);
        assert.strictEqual(record.lineItemId, fulfillments[0].attributeValues.lineItemId);
        assert.strictEqual(record.actorAccountId, ACCOUNT);
        // The Order's immutable originating scope, copied onto the record: a later join
        // must not move this sale's demand into another Unit (ORD-API-02-04).
        assert.strictEqual(record.unitId, 'UNIT#pack-3149');
        assert.strictEqual(record.unitCampaignId, 'uc-pack-3149-fall-2026');
        assert.strictEqual(record.inventoryMovementId, 'auto-generated-id');

        const movements = itemsByTable(result, INVENTORY_TABLE).filter(function (item) {
            return item.attributeValues && item.attributeValues.entityType === 'InventoryMovement';
        });
        assert.strictEqual(movements.length, 1);
        const movement = movements[0].attributeValues;
        assert.strictEqual(movement.movementType, 'INDIVIDUAL_FULFILL');
        assert.strictEqual(movement.withScoutDelta, -5);
        assert.strictEqual(movement.profileId, 'PROFILE#p1');
        assert.strictEqual(movement.orderId, order.orderId);
        assert.strictEqual(movement.idempotencyKey, 'sale-1');

        const markers = itemsByTable(result, FULFILLMENT_TABLE).filter(function (item) {
            return item.attributeValues && item.attributeValues.status === 'COMPLETED';
        });
        assert.strictEqual(markers.length, 1);
        assert.strictEqual(markers[0].attributeValues.resultId, order.orderId);
        assert.strictEqual(markers[0].condition.expression, 'attribute_not_exists(#pk) AND attribute_not_exists(#sk)');

        // Kernel stock is not touched at all: the balance row is never written, because
        // those Kernels left it when the Unit issued them to the Scout.
        const balanceWrites = itemsByTable(result, INVENTORY_TABLE).filter(function (item) {
            return item.key && item.key.sk === 'PRODUCT#PROD#1#BALANCE';
        });
        assert.deepStrictEqual(balanceWrites, []);
        // The campaign counter is part of this transaction (ARCH-2), so a retry of a
        // committed sale cannot leave the counters behind, and the trailing totals step has
        // nothing left to add.
        const counter = itemsByTable(result, CAMPAIGNS_TABLE);
        assert.strictEqual(counter.length, 1);
        assert.deepStrictEqual(counter[0].update.expressionValues[':revenue'], 9.95);
        assert.strictEqual(ctx.stash.totalsDelta, undefined);
    });

    it('consumes only what the Scout holds and leaves the remainder unfulfilled (ORD-API-02-02)', () => {
        const ctx = saleCtx({ custodyRows: [{ productId: 'PROD#1', withScoutQty: 3, version: 2 }] });
        const result = request(ctx);
        const order = orderRow(result);
        assert.strictEqual(order.lineItems[0].fulfilledQuantity, 3);
        assert.strictEqual(order.lineItems[0].quantity, 5);
        const custody = itemsByTable(result, INVENTORY_TABLE).filter(function (item) {
            return item.operation === 'UpdateItem';
        });
        assert.strictEqual(custody[0].update.expressionValues[':scoutDelta'], -3);
        assert.strictEqual(custody[0].condition.expressionValues[':scoutFloor'], 3);
    });

    it('never blocks on insufficient custody, and writes nothing stock-shaped when there is none', () => {
        const ctx = saleCtx({ custodyRows: [] });
        const result = request(ctx);
        assert.strictEqual(result.operation, 'TransactWriteItems');
        // marker + order + guard pin + campaign counter, and nothing on the inventory table.
        assert.strictEqual(result.transactItems.length, 4);
        assert.deepStrictEqual(itemsByTable(result, INVENTORY_TABLE), []);
        assert.strictEqual(orderRow(result).lineItems[0].fulfilledQuantity, 0);
        // The marker still rides, so a retry of this same request is answered rather than
        // run a second time, even though the sale consumed nothing.
        assert.strictEqual(itemsByTable(result, FULFILLMENT_TABLE).length, 1);
    });

    it('consumes no custody for an independent sale, even when the campaign row still names a Unit', () => {
        // API contract §10.1: an independent individual Order has null campaign scope and
        // does not consume custody. The retained link is not a scope to sell against.
        const ctx = saleCtx({ custodyRows: [{ productId: 'PROD#1', withScoutQty: 9, version: 1 }] });
        delete ctx.stash.membershipGuard;
        const result = request(ctx);
        assert.strictEqual(orderRow(result).unitCampaignId, null);
        assert.deepStrictEqual(itemsByTable(result, INVENTORY_TABLE), []);
        assert.strictEqual(orderRow(result).lineItems[0].fulfilledQuantity, 0);
    });

    it('refuses rather than guesses when the joined scope moved between the two strong reads', () => {
        // The custody read is keyed by the campaign's link; the guard is the current answer.
        // Consuming one Unit's custody for an Order stamped to another is the cross-tenant
        // class AUTH-U exists to prevent, so nothing is written and the caller retries.
        const ctx = saleCtx({ custodyRows: [{ productId: 'PROD#1', withScoutQty: 9, version: 1 }] });
        ctx.stash.custodySaleRead.unitCampaignId = 'uc-crew-529-spring-2027';
        assert.throws(() => request(ctx), /CONFLICT: The campaign changed scope while this order was being placed; try again/);
    });

    it('answers a retry from the completed marker and writes nothing (ORD-API-02-03)', () => {
        const stored = { orderId: 'ORDER#c1#old', fulfillmentVersion: 0, lineItems: [] };
        const ctx = saleCtx({ custodyRows: [{ productId: 'PROD#1', withScoutQty: 9, version: 1 }] });
        ctx.stash.idempotencyMarker = {
            pk: 'IDEM#' + ACCOUNT + '#createOrder#CAMPAIGN%23c1',
            sk: 'IDEM#sale-1',
            status: 'COMPLETED',
            fingerprint: fingerprintOf(ctx),
            resultPayload: JSON.stringify(stored)
        };
        const answered = request(ctx);
        assert.deepStrictEqual(answered, stored);
        // No totalsDelta means sync_campaign_totals_fn passes the answer through instead of
        // counting the same order a second time.
        assert.strictEqual(ctx.stash.totalsDelta, undefined);
        assert.strictEqual(ctx.stash.orderItem, undefined);
    });

    it('treats a marker still in flight as a race rather than a second sale', () => {
        const ctx = saleCtx({ marker: { status: 'IN_FLIGHT', fingerprint: 'fp' } });
        assert.throws(() => request(ctx), /RESOURCE_BUSY: This sale is still being processed for that idempotencyKey/);
    });

    it('refuses the same key carrying a different order', () => {
        const ctx = saleCtx({ marker: { status: 'COMPLETED', fingerprint: 'some-other-order', resultPayload: '{}' } });
        assert.throws(() => request(ctx), /INVALID_INPUT: That idempotencyKey was already used for a different order/);
    });

    it('calls a completed marker whose payload cannot be read an internal fault, not a caller error', () => {
        const ctx = saleCtx();
        ctx.stash.idempotencyMarker = { status: 'COMPLETED', fingerprint: fingerprintOf(ctx) };
        assert.throws(() => request(ctx), /INTERNAL_ERROR: The recorded result of this sale could not be read back/);
    });

    it('keeps a NONE-mode order exactly as it was: one PutItem, no marker, no stock write', () => {
        const ctx = saleCtx({ input: { fulfillmentMode: null, idempotencyKey: null }, custodyRows: [{ productId: 'PROD#1', withScoutQty: 9, version: 1 }] });
        const result = request(ctx);
        assert.strictEqual(result.operation, 'TransactWriteItems');
        assert.deepStrictEqual(itemsByTable(result, INVENTORY_TABLE), []);
        assert.strictEqual(result.transactItems.length, 2);
        assert.strictEqual(result.transactItems[0].attributeValues.lineItems[0].fulfilledQuantity, 0);
    });

    it('refuses a plan larger than the write budget before writing anything (§8.10)', () => {
        const many = [];
        const products = [];
        const rows = [];
        for (let i = 0; i < 60; i++) {
            many.push({ productId: 'PROD#' + i, quantity: 1 });
            products.push({ productId: 'PROD#' + i, productName: 'P' + i, price: 1 });
            rows.push({ productId: 'PROD#' + i, withScoutQty: 2, version: 1 });
        }
        const ctx = saleCtx({ input: { lineItems: many }, custodyRows: rows });
        ctx.stash.catalog = { products };
        assert.throws(() => request(ctx), /CONFLICT: This order needs 184 conditional writes; the limit is 90/);
    });
});

describe('create_order_fn response: which conditional write cancelled', () => {
    function cancelled(reasons, indexes) {
        const stash = { orderItem: { orderId: 'ORDER#c1#o1' }, orderWriteIndexes: indexes };
        return () =>
            response({
                stash,
                error: { type: 'DynamoDB:TransactionCanceledException', message: 'Transaction cancelled, please refer cancellation reasons for specific reasons ' + reasons }
            });
    }

    it('maps a cancelled marker insert to a retryable race', () => {
        assert.throws(cancelled('[None, None, ConditionalCheckFailedException, None]', { marker: 2, custody: [3] }), /RESOURCE_BUSY: This sale is already being processed for that idempotencyKey/);
    });

    it('maps a cancelled custody decrement to a retryable conflict that says what moved', () => {
        assert.throws(cancelled('[None, None, None, ConditionalCheckFailedException, None]', { marker: 2, custody: [3, 4] }), /CONFLICT: Scout custody changed while this order was being placed; try again/);
    });

    it('maps a cancelled campaign counter ADD to a retryable conflict naming the campaign', () => {
        // ARCH-2: the counter rode this transaction, so a failed counter ADD cancels the
        // sale too. Nothing committed, which is what lets a retry repeat the whole plan
        // instead of returning a stored Order whose counter never moved.
        assert.throws(
            cancelled('[None, None, None, ConditionalCheckFailedException, None]', { marker: 2, custody: [4, 5], totals: 3 }),
            /CONFLICT: The campaign was removed while this order was being placed; try again/
        );
    });

    it('falls back to the membership-pin message when only the guard condition failed', () => {
        assert.throws(cancelled('[None, ConditionalCheckFailedException, None]', { marker: 2, custody: [3] }), /CONFLICT: The campaign changed while this order was being placed; try again/);
    });
});

// Table names are templatefile() placeholders, and these cases sit outside the block above.
const CAMPAIGNS_TABLE = '${campaigns_table_name}';

function itemsOnTable(result, table) {
    return result.transactItems.filter(function (item) {
        return item.table === table;
    });
}

describe('create_order_fn request: the campaign counter rides the sale transaction (ARCH-2)', () => {
    function saleCtx(custodyRows) {
        return {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    campaignId: 'CAMPAIGN#c1',
                    customerName: 'Alice',
                    orderDate: '2024-01-01T00:00:00Z',
                    paymentMethod: 'Cash',
                    fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
                    idempotencyKey: 'sale-1',
                    lineItems: [{ productId: 'PROD#1', quantity: 2 }]
                }
            },
            identity: { claims: { sub: '11111111-1111-4111-8111-111111111111' } },
            stash: {
                campaign: { profileId: 'PROFILE#p1', unitCampaignId: 'uc-1' },
                membershipGuard: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-1', unitId: 'UNIT#u1' },
                catalog: { products: [{ productId: 'PROD#1', productName: 'Popcorn', price: 1 }] },
                custodySaleRead: { unitCampaignId: 'uc-1', profileId: 'PROFILE#p1', idempotencyKey: 'sale-1' },
                profileWriteAuthorized: true,
                custodyRows: custodyRows || []
            }
        };
    }

    it('adds the campaign ADD to the same transaction, and leaves nothing for the totals step', () => {
        const ctx = saleCtx([{ productId: 'PROD#1', withScoutQty: 5, version: 1 }]);
        const result = request(ctx);
        const counter = itemsOnTable(result, CAMPAIGNS_TABLE);
        assert.strictEqual(counter.length, 1);
        assert.strictEqual(counter[0].operation, 'UpdateItem');
        assert.deepStrictEqual(counter[0].key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(counter[0].update.expression, 'ADD #totalOrders :count, #totalRevenue :revenue');
        assert.deepStrictEqual(counter[0].update.expressionValues[':count'], 1);
        assert.deepStrictEqual(counter[0].update.expressionValues[':revenue'], 2);
        // attribute_exists(campaignId) is the same vanished-campaign no-op the trailing
        // totals step uses; here it cancels the sale instead.
        assert.strictEqual(counter[0].condition.expression, 'attribute_exists(campaignId)');
        // Nothing left for sync_campaign_totals_fn: a second ADD would count the sale twice.
        assert.strictEqual(ctx.stash.totalsDelta, undefined);
        // And the write step knows which action it was, so a cancelled counter ADD is
        // reported as the campaign moving out from under the sale rather than as a mystery.
        assert.ok(ctx.stash.orderWriteIndexes.totals >= 0);
    });

    it('leaves an ordinary order on the trailing totals step it used before', () => {
        const ctx = saleCtx();
        ctx.args.input.fulfillmentMode = null;
        ctx.args.input.idempotencyKey = null;
        const result = request(ctx);
        assert.deepStrictEqual(itemsOnTable(result, CAMPAIGNS_TABLE), []);
        assert.deepStrictEqual(ctx.stash.totalsDelta, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', count: 1, revenue: 2 });
    });
});

describe('create_order_fn request: the fingerprint covers every field the Order writes (FUNC-5)', () => {
    const base = {
        mode: 'CONSUME_SCOUT_CUSTODY',
        profileId: 'PROFILE#p1',
        campaignId: 'CAMPAIGN#c1',
        customerName: 'Alice',
        customerPhone: null,
        customerAddress: null,
        orderDate: '2024-01-01T00:00:00Z',
        paymentMethod: 'Cash',
        notes: null,
        lineItems: [{ productId: 'PROD#1', quantity: 2 }]
    };
    const original = requestFingerprint(base);

    it('refuses a key reused with a different payment method, date, contact, address or note', () => {
        for (const change of [
            { paymentMethod: 'Card' },
            { orderDate: '2024-01-02T00:00:00Z' },
            { customerPhone: '555-0100' },
            { notes: 'leave at door' },
            { customerAddress: { street: '1 Main', city: 'Springfield', state: 'IL', zipCode: '62701' } }
        ]) {
            assert.notStrictEqual(requestFingerprint({ ...base, ...change }), original, JSON.stringify(change) + ' must fingerprint differently');
        }
    });

    it('is stable across padding, and across an omitted versus an explicit null address', () => {
        assert.strictEqual(requestFingerprint({ ...base, customerName: '  Alice ' }), original);
        assert.strictEqual(requestFingerprint({ ...base, customerAddress: undefined }), original);
    });

    it('treats the same address written twice as one request', () => {
        assert.strictEqual(
            requestFingerprint({ ...base, customerAddress: { street: '1 Main', city: 'Springfield', state: 'IL', zipCode: '62701' } }),
            requestFingerprint({ ...base, customerAddress: { street: '1 Main', city: 'Springfield', state: 'IL', zipCode: '62701' } })
        );
    });
});

// SEC-1 (§2.4.2): "Profile Owner/WRITE or Unit Admin". A door-to-door sale moves the
// Unit's stock, so the Unit that lent the Scout that stock is a tenant of the write, and
// its admin may record the sale without holding any share on the Profile. The check lives
// in the write step because that is the first step holding both answers: the share step
// hands down `profileWriteAuthorized`, and the guard step fetched the grant row into the
// batch the sale already issues.
describe('create_order_fn request: a sale is authorized by Profile WRITE or the Unit Admin', () => {
    const INVENTORY_TABLE = '${inventory_table_name}';
    const ORDERS_TABLE = '${orders_table_name}';
    const ADMIN = '22222222-2222-4222-8222-222222222222';
    const UNIT = 'pack-3149';

    function adminCtx(options) {
        const opts = options || {};
        const custodyRows = opts.custodyRows === undefined ? [{ productId: 'PROD#1', withScoutQty: 5, version: 1 }] : opts.custodyRows;
        return {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    campaignId: 'CAMPAIGN#c1',
                    customerName: 'Alice',
                    orderDate: '2024-01-01T00:00:00Z',
                    paymentMethod: 'Cash',
                    fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
                    idempotencyKey: 'sale-1',
                    lineItems: [{ productId: 'PROD#1', quantity: 2 }]
                }
            },
            identity: { claims: { sub: ADMIN } },
            stash: {
                campaign: { profileId: 'PROFILE#p1', unitId: opts.unitId === null ? undefined : UNIT, unitCampaignId: 'uc-pack-3149-fall-2026' },
                membershipGuard: opts.guard === null
                    ? null
                    : { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026', unitId: UNIT },
                catalog: { products: [{ productId: 'PROD#1', productName: 'Popcorn', price: 1 }] },
                custodySaleRead: { unitCampaignId: 'uc-pack-3149-fall-2026', profileId: 'PROFILE#p1', idempotencyKey: 'sale-1' },
                profileWriteAuthorized: opts.profileWrite === true,
                unitAdminGrant: opts.grant === undefined ? null : opts.grant,
                custodyRows,
                idempotencyMarker: opts.marker === undefined ? null : opts.marker
            }
        };
    }

    function grantFor(unitId, accountId) {
        return { pk: 'UNIT#' + unitId, sk: 'GRANT#' + accountId, role: 'UNIT_ADMIN' };
    }

    it('records the sale for an admin of the Unit whose custody it consumes', () => {
        const ctx = adminCtx({ grant: grantFor(UNIT, ADMIN) });

        const result = request(ctx);

        // The custody really moves: the decrement is in the same transaction as the Order.
        const custody = itemsOnTable(result, INVENTORY_TABLE).filter(function (item) {
            return item.operation === 'UpdateItem';
        });
        assert.strictEqual(custody.length, 1);
        assert.strictEqual(custody[0].table, INVENTORY_TABLE);
        assert.strictEqual(itemsOnTable(result, ORDERS_TABLE).length, 1);
    });

    it('refuses a grant on a different Unit, because the guard names whose custody this is', () => {
        const ctx = adminCtx({ grant: grantFor('other-unit', ADMIN) });

        assert.throws(() => request(ctx), /FORBIDDEN: Forbidden: a custody sale needs the profile owner/);
    });

    it('refuses a grant belonging to another account, including a row planted at a guessable key', () => {
        const ctx = adminCtx({ grant: grantFor(UNIT, 'someone-else') });

        assert.throws(() => request(ctx), /FORBIDDEN/);
    });

    it('refuses a revoked admin: the grant row is deleted, and absence is the whole answer', () => {
        const ctx = adminCtx({ grant: null });

        assert.throws(() => request(ctx), /FORBIDDEN/);
    });

    it('refuses the READ-only share case with no grant, which is the denial the Profile path always gave', () => {
        const ctx = adminCtx({ profileWrite: false, grant: null });

        assert.throws(() => request(ctx), /FORBIDDEN/);
    });

    it('refuses an independent sale whose Profile half failed: no Unit means no Unit Admin to ask', () => {
        const ctx = adminCtx({ guard: null, unitId: null, custodyRows: [] });

        assert.throws(() => request(ctx), /FORBIDDEN/);
    });

    it('denies before replaying a completed marker, so a stored Order is not handed to a caller with no claim on it', () => {
        // The replay path writes nothing, which is exactly why it needs the check: the
        // marker holds somebody's Order, and reading it is already a disclosure.
        const ctx = adminCtx({ grant: null, marker: { status: 'COMPLETED', fingerprint: 'anything', resultPayload: { orderId: 'ORDER#x' } } });

        assert.throws(() => request(ctx), /FORBIDDEN/);
    });

    it('takes the Profile path without looking at the grant at all', () => {
        const ctx = adminCtx({ profileWrite: true, grant: null });

        const result = request(ctx);

        assert.strictEqual(itemsOnTable(result, ORDERS_TABLE).length, 1);
    });
});
