import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './public_create_order_pipeline_resolver.js';

describe('public_create_order_pipeline_resolver request', () => {
    it('is an empty request: the pipeline does the work', () => {
        assert.deepStrictEqual(request({}), {});
    });
});

describe('public_create_order_pipeline_resolver response', () => {
    it('propagates a datastore error from a later step', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('fails loudly when the write step produced no receipt', () => {
        assert.throws(() => response({}), /INTERNAL_ERROR: Order could not be placed/);
        assert.throws(() => response({ prev: { result: { totalAmount: 1 } } }), /INTERNAL_ERROR: Order could not be placed/);
    });

    it('passes the write step receipt through unchanged', () => {
        const receipt = { orderId: 'ORDER#c1#s', receiptUrl: '/r/c1/s/t', totalAmount: 1 };
        assert.strictEqual(response({ prev: { result: receipt } }), receipt);
    });
});
