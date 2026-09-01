import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_order_fn.js';

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
      /BadRequest: Order must have at least one line item/
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
      /BadRequest: Quantity must be at least 1/
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
      /BadRequest: Product PROD#UNKNOWN not found in catalog/
    );
  });
});

describe('create_order_fn response', () => {
  it('returns the order result', () => {
    const order = { orderId: 'ORDER#1', campaignId: 'CAMPAIGN#1' };
    const result = response({ result: order });
    assert.deepStrictEqual(result, order);
  });

  it('throws on AppSync error', () => {
    assert.throws(
      () => response({ error: { message: 'Failed', type: 'DynamoDB' } }),
      /DynamoDB: Failed/
    );
  });
});
