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

  it('answers a failed version condition as a retryable CONFLICT, not as a caller error', () => {
    assert.throws(
      () => response({ error: { message: 'The conditional check failed.', type: 'DynamoDB:ConditionalCheckFailedException' } }),
      /CONFLICT: This order changed while the edit was being saved; re-read it and try again/
    );
  });

  it('passes any other datasource error through unchanged', () => {
    assert.throws(
      () => response({ error: { message: 'Throttling', type: 'DynamoDB:ProvisionedThroughputExceededException' } }),
      /DynamoDB:ProvisionedThroughputExceededException: Throttling/
    );
  });
});

describe('update_order_fn version guard: the edit advances the version it pinned', () => {
  function editAt(fulfillmentVersion) {
    const order = {
      campaignId: 'CAMPAIGN#c1',
      orderId: 'ORDER#o1',
      lineItems: [{ productId: 'PROD1', quantity: 2, lineItemId: 'LINE#1', fulfilledQuantity: 0 }]
    };
    if (fulfillmentVersion !== undefined) {
      order.fulfillmentVersion = fulfillmentVersion;
    }
    return {
      stash: {
        order: order,
        catalog: { products: [{ productId: 'PROD1', productName: 'Popcorn', price: 1 }] }
      },
      args: { input: { lineItems: [{ productId: 'PROD1', quantity: 3 }] } }
    };
  }

  it('pins the version of a pre-Wave-3 row and stamps 1', () => {
    const result = request(editAt(undefined));
    assert.strictEqual(result.condition.expressionValues[':expectedFulfillmentVersion'], 0);
    assert.match(result.condition.expression, /attribute_not_exists\(#fulfillmentVersion\) OR #fulfillmentVersion = :expectedFulfillmentVersion/);
    assert.match(result.condition.expression, /AND attribute_exists\(#orderId\)/);
    assert.strictEqual(result.update.expressionValues[':nextFulfillmentVersion'], 1);
  });

  it('stamps one more than the version it pins, for a row part-way through its history', () => {
    const result = request(editAt(7));
    assert.strictEqual(result.condition.expressionValues[':expectedFulfillmentVersion'], 7);
    assert.strictEqual(result.condition.expressionValues[':expectedFulfillmentVersion'], 7);
    // A non-zero version has no `attribute_not_exists` escape: the row must say 7.
    assert.doesNotMatch(result.condition.expression, /attribute_not_exists/);
    assert.strictEqual(result.update.expressionValues[':nextFulfillmentVersion'], 8);
  });

  it('walks successive edits 0 -> 1 -> 2 -> 3 without ever moving the version backwards', () => {
    let version = undefined;
    const stamped = [];
    for (let edit = 0; edit < 3; edit = edit + 1) {
      const result = request(editAt(version));
      const pinned = result.condition.expressionValues[':expectedFulfillmentVersion'];
      const next = result.update.expressionValues[':nextFulfillmentVersion'];
      assert.strictEqual(next, pinned + 1, 'edit ' + edit + ' must advance the version it pinned');
      stamped.push(next);
      version = next;
    }
    assert.deepStrictEqual(stamped, [1, 2, 3]);
  });

  it('gives an edit and a fulfillment the same serialization point, in either race order', () => {
    // Both writers pin the version they read and stamp the next one, so whichever lands
    // first makes the other's condition fail. The edit half is this resolver; the
    // fulfillment half is `fulfillment_version_condition` on the Python side, and
    // lib/fulfillment_version.test.js pins the shared spelling.
    const result = request(editAt(2));
    assert.strictEqual(result.update.expressionValues[':nextFulfillmentVersion'], 3);
    assert.strictEqual(result.condition.expression, '#fulfillmentVersion = :expectedFulfillmentVersion AND attribute_exists(#orderId)');
    assert.deepStrictEqual(result.condition.expressionNames, {
      '#fulfillmentVersion': 'fulfillmentVersion',
      '#orderId': 'orderId'
    });
  });

  it('refuses an update in which two rows name the same stored line', () => {
    // Through the mutation, not just the helper: the duplicate would otherwise reach the
    // row with one line's fulfilled quantity on two lines.
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
          fulfillmentVersion: 1,
          lineItems: [{ productId: 'PROD1', quantity: 2, lineItemId: 'LINE#1', fulfilledQuantity: 2 }]
        },
        catalog: { products: [{ productId: 'PROD1', productName: 'Popcorn', price: 1 }] }
      },
      args: {
        input: {
          lineItems: [
            { productId: 'PROD1', quantity: 2, lineItemId: 'LINE#1' },
            { productId: 'PROD1', quantity: 1, lineItemId: 'LINE#1' }
          ]
        }
      }
    };
    assert.throws(() => request(ctx), /INVALID_INPUT: lineItemId LINE#1 appears more than once in this update/);
  });
});
