import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './public_create_order_pipeline_resolver.js';

// #679 write slice: the publicCreateOrder root resolver passes the write step's
// composed receipt through, and fails loudly rather than returning null on a
// non-nullable mutation field.

describe('public_create_order_pipeline_resolver', () => {
    it('passes the write step result through unchanged', () => {
        const receipt = {
            orderId: 'ORDER#c1#s1',
            receiptUrl: '/r/c1/s1/token',
            totalAmount: 9,
            buyerEmailProvided: true,
            confirmationEmailSent: false
        };

        const result = response({ prev: { result: receipt }, error: null, stash: {} });

        assert.deepStrictEqual(result, receipt);
    });

    it('surfaces a pipeline error unchanged', () => {
        const ctx = { prev: { result: null }, error: { type: 'PUBLIC_ORDER_LIMIT_EXCEEDED', message: 'This campaign has reached its public order limit' }, stash: {} };
        assert.throws(() => response(ctx), /PUBLIC_ORDER_LIMIT_EXCEEDED/);
    });

    it('raises INTERNAL_ERROR rather than returning null for a missing receipt', () => {
        const ctx = { prev: { result: null }, error: null, stash: {} };
        assert.throws(() => response(ctx), /INTERNAL_ERROR: Order could not be placed/);
    });

    it('raises INTERNAL_ERROR when the last function returned no order id', () => {
        const ctx = { prev: { result: { totalAmount: 9 } }, error: null, stash: {} };
        assert.throws(() => response(ctx), /INTERNAL_ERROR/);
    });

    it('requests nothing itself - every read belongs to a pipeline function', () => {
        assert.deepStrictEqual(request({ stash: {}, args: {} }), {});
    });
});
