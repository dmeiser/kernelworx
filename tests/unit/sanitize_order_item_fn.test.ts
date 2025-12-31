import { describe, test, expect } from 'vitest';
import * as fn from '../../cdk/cdk/resolvers/sanitize_order_item_fn.js';

describe('sanitize_order_item_fn', () => {
  test('removes productName object and coerces quantity', () => {
    const ctx: any = { arguments: { input: { lineItems: [{ productId: 'PRODUCT#1', quantity: '2', productName: {} }] } }, prev: {} };
    const req = fn.request(ctx as any);
    expect(ctx.arguments.input.lineItems[0].productName).toBeUndefined();
    expect(ctx.arguments.input.lineItems[0].quantity).toBe(2);
  });
});
