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
      /BadRequest: Order must have at least one line item/
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
      /BadRequest: Order must have at least one line item/
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
      /BadRequest: Order must have at least one line item/
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
