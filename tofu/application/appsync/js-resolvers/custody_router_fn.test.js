// Tests for the custody router step (Show & Sell wave 3).
import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './custody_router_fn.js';

describe('custody_router_fn request', () => {
  it('invokes the order-operations Lambda with the full context', () => {
    const ctx = { args: { input: { fulfillmentMode: 'NONE' } }, stash: { campaign: {} } };
    const result = request(ctx);
    assert.strictEqual(result.operation, 'Invoke');
    assert.deepStrictEqual(result.payload, ctx);
  });
});

describe('custody_router_fn response', () => {
  it('continues the pipeline for the NONE path', () => {
    const prev = { orderId: 'ORDER#x' };
    const result = response({ result: { __continue__: true }, prev: { result: prev } });
    assert.deepStrictEqual(result, prev);
  });

  it('early-returns the custody order, ending the pipeline', () => {
    const order = { orderId: 'ORDER#custody', origin: { kind: 'UNIT_CAMPAIGN' } };
    const result = response({ result: order, prev: { result: {} } });
    // runtime.earlyReturn is identity in the test mock; production ends the
    // pipeline with this value.
    assert.deepStrictEqual(result, order);
  });

  it('surfaces pipeline errors', () => {
    assert.throws(
      () => response({ error: { message: 'boom', type: 'Conflict' } }),
      /Conflict: boom/
    );
  });
});
