import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_order_fn.js';

describe('update_order_fn request', () => {
  it('rejects an empty lineItems array', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: {
          products: [
            { productId: 'PROD1', productName: 'Popcorn', price: 10.0 },
          ],
        },
      },
      args: {
        input: {
          lineItems: [],
        },
      },
    };

    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: Order must have at least one line item/
    );
  });

  it('accepts a non-empty lineItems array and calculates totals with integer cents', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: {
          products: [
            { productId: 'PROD1', productName: 'Popcorn', price: 1.99 },
            { productId: 'PROD2', productName: 'Caramel', price: 0.10 },
            { productId: 'PROD3', productName: 'Cheese', price: 0.20 },
          ],
        },
      },
      args: {
        input: {
          lineItems: [
            { productId: 'PROD1', quantity: 3 },
            { productId: 'PROD2', quantity: 1 },
            { productId: 'PROD3', quantity: 1 },
          ],
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
    assert.strictEqual(result.key.orderId, 'ORDER#o1');
    assert.match(result.update.expression, /lineItems = :lineItems/);
    assert.match(result.update.expression, /totalAmount = :totalAmount/);

    const lineItems = result.update.expressionValues[':lineItems'];
    assert.strictEqual(lineItems[0].subtotal, 5.97);
    assert.strictEqual(lineItems[1].subtotal, 0.1);
    assert.strictEqual(lineItems[2].subtotal, 0.2);
    // 5.97 + 0.10 + 0.20 = 6.27 exactly
    assert.strictEqual(result.update.expressionValues[':totalAmount'], 6.27);
  });

  it('rejects a null lineItems value', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: null,
      },
      args: {
        input: {
          lineItems: null,
        },
      },
    };

    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: Order must have at least one line item/
    );
  });

  it('rejects a non-array lineItems value', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: null,
      },
      args: {
        input: {
          lineItems: 'not-an-array',
        },
      },
    };

    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: Order must have at least one line item/
    );
  });

  it('does not require lineItems when updating other fields', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: null,
      },
      args: {
        input: {
          customerName: 'Jane Doe',
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.match(result.update.expression, /customerName = :customerName/);
  });

  it('stashes a count-zero totals delta when lineItems change the amount (#746)', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
          profileId: 'PROFILE#p1',
          totalAmount: 5.97,
        },
        catalog: {
          products: [{ productId: 'PROD1', productName: 'Popcorn', price: 10.0 }],
        },
      },
      args: {
        input: {
          lineItems: [{ productId: 'PROD1', quantity: 1 }],
        },
      },
    };

    request(ctx);

    assert.deepStrictEqual(ctx.stash.totalsDelta, {
      profileId: 'PROFILE#p1',
      campaignId: 'CAMPAIGN#c1',
      count: 0,
      revenue: 4.03,
    });
  });

  it('rounds the float tail out of the totals delta (#746)', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
          profileId: 'PROFILE#p1',
          totalAmount: 19.99,
        },
        catalog: {
          products: [{ productId: 'PROD1', productName: 'Popcorn', price: 20.0 }],
        },
      },
      args: {
        input: {
          lineItems: [{ productId: 'PROD1', quantity: 1 }],
        },
      },
    };

    request(ctx);

    // 20.00 - 19.99 is 0.010000000000000231 in IEEE-754; the delta must be cents.
    assert.strictEqual(ctx.stash.totalsDelta.revenue, 0.01);
  });

  it('stashes no totals delta when lineItems reproduce the current amount (#746)', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
          profileId: 'PROFILE#p1',
          totalAmount: 5.97,
        },
        catalog: {
          products: [{ productId: 'PROD1', productName: 'Popcorn', price: 1.99 }],
        },
      },
      args: {
        input: {
          lineItems: [{ productId: 'PROD1', quantity: 3 }],
        },
      },
    };

    request(ctx);

    assert.strictEqual(ctx.stash.totalsDelta, undefined);
  });
});

// The order lifecycle slice: the seller's "payment confirmed" transition.
describe('update_order_fn status transition', () => {
  const publicOrder = {
    campaignId: 'CAMPAIGN#c1',
    orderId: 'ORDER#o1',
    profileId: 'PROFILE#p1',
    orderSource: 'PUBLIC',
    status: 'NEW',
    receiptToken: 'tok-abc',
  };

  const ctxFor = (order, input) => ({
    stash: { order, catalog: null },
    args: { input },
  });

  it('sets status CONFIRMED on a public order and bumps updatedAt', () => {
    const result = request(ctxFor(publicOrder, { status: 'CONFIRMED' }));

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.match(result.update.expression, /#status = :status/);
    assert.match(result.update.expression, /updatedAt = :updatedAt/);
    assert.strictEqual(result.update.expressionValues[':status'], 'CONFIRMED');
    // `status` is a DynamoDB reserved word: the attribute must be addressed
    // through the expression-attribute-name map, never bare in the expression
    // (a bare SET status = ... fails at runtime with "reserved keyword").
    assert.deepStrictEqual(result.update.expressionNames, {
        '#status': 'status',
        '#confirmedBy': 'confirmedBy',
        '#confirmedAt': 'confirmedAt'
    });
    assert.ok(
        !/(^|[^#:])\bstatus\b/.test(result.update.expression),
        `no bare status attribute in: ${result.update.expression}`,
    );
    // The write is a SET of status only: it must never touch the capability or
    // the provenance attributes.
    assert.doesNotMatch(result.update.expression, /receiptToken/);
    assert.doesNotMatch(result.update.expression, /orderSource/);
    // SEC-13: confirmedBy and confirmedAt must be set for CONFIRMED transitions
    assert.match(result.update.expression, /#confirmedBy = :confirmedBy/);
    assert.match(result.update.expression, /#confirmedAt = :confirmedAt/);
    assert.ok(typeof result.update.expressionValues[':confirmedBy'] === 'string' && result.update.expressionValues[':confirmedBy'].startsWith('ACCOUNT#'));
    assert.ok(typeof result.update.expressionValues[':confirmedAt'] === 'string' && result.update.expressionValues[':confirmedAt'].includes('T'));
  });

  it('rejects status on an order that is not a public order', () => {
    const authenticated = { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#o1', profileId: 'PROFILE#p1' };

    assert.throws(
      () => request(ctxFor(authenticated, { status: 'CONFIRMED' })),
      /INVALID_INPUT: status can only be set on public orders/,
    );
  });

  it('rejects any status value other than CONFIRMED', () => {
    assert.throws(
      () => request(ctxFor(publicOrder, { status: 'NEW' })),
      /INVALID_INPUT: Only CONFIRMED can be set on an order status/,
    );
  });

  it('rejects the transition on an order that is already CONFIRMED (one-way)', () => {
    const confirmed = { ...publicOrder, status: 'CONFIRMED' };

    assert.throws(
      () => request(ctxFor(confirmed, { status: 'CONFIRMED' })),
      /INVALID_INPUT: Order is already confirmed; there is no path back from CONFIRMED/,
    );
  });

  it('rejects an explicit null status rather than clearing it', () => {
    assert.throws(
      () => request(ctxFor(publicOrder, { status: null })),
      /INVALID_INPUT: status cannot be null; omit the field to leave the status unchanged/,
    );
  });

  it('leaves status, receiptToken and orderSource untouched on an ordinary edit', () => {
    const confirmed = { ...publicOrder, status: 'CONFIRMED' };
    const result = request(ctxFor(confirmed, { notes: 'paid by cheque' }));

    assert.match(result.update.expression, /notes = :notes/);
    for (const attribute of ['status', 'receiptToken', 'orderSource']) {
      assert.ok(
        !result.update.expression.includes(attribute),
        `an ordinary edit must never write ${attribute}`,
      );
    }
    // SEC-13: confirmedBy and confirmedAt must NOT be set for non-status edits
    assert.doesNotMatch(result.update.expression, /confirmedBy/);
    assert.doesNotMatch(result.update.expression, /confirmedAt/);
  });

  it('performs no identity check of its own (authorization lives in the pipeline)', () => {
    // The updateOrder pipeline runs verify_profile_write_access + _step2 and
    // check_share_permissions before this function (pinned by
    // tests/unit/test_appsync_pipeline_functions.py). This write step must not
    // grow a second, divergent authorization path.
    const ctx = { stash: { order: publicOrder, catalog: null }, args: { input: { status: 'CONFIRMED' } }, identity: { sub: 'user-123' } };

    const result = request(ctx);
    assert.match(result.update.expression, /#status = :status/);
    assert.deepStrictEqual(result.update.expressionNames, {
        '#status': 'status',
        '#confirmedBy': 'confirmedBy',
        '#confirmedAt': 'confirmedAt'
    });
  });
});

describe('update_order_fn response', () => {
  it('returns the order result', () => {
    const order = { orderId: 'ORDER#1', campaignId: 'CAMPAIGN#1' };
    const result = response({ result: order });
    assert.deepStrictEqual(result, order);
  });

  it('throws on AppSync error', () => {
    assert.throws(
      () => response({ error: { message: 'Update failed', type: 'DynamoDB' } }),
      /DynamoDB: Update failed/
    );
  });
});
