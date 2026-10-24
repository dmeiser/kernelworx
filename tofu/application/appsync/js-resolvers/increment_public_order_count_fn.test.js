import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './increment_public_order_count_fn.js';
import { PUBLIC_ORDER_CAP } from './lib/public_order.js';

describe('increment_public_order_count request', () => {
    it('refuses a missing stash with the limit error (wiring fault)', () => {
        assert.throws(() => request({ stash: {} }), /PUBLIC_ORDER_LIMIT_EXCEEDED: This campaign has reached its public order limit/);
    });

    it('issues an atomic ADD guarded by the cap condition', () => {
        const req = request({ stash: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' } });
        assert.strictEqual(req.operation, 'UpdateItem');
        assert.deepStrictEqual(req.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(req.update.expression, 'ADD #publicOrderCount :one');
        assert.deepStrictEqual(req.update.expressionValues, { ':one': 1 });
        assert.strictEqual(req.condition.expression, 'attribute_exists(campaignId) AND (attribute_not_exists(#publicOrderCount) OR #publicOrderCount < :cap)');
        assert.deepStrictEqual(req.condition.expressionValues, { ':cap': PUBLIC_ORDER_CAP });
    });
});

describe('increment_public_order_count response', () => {
    it('maps a conditional check failure to the limit error (the cap was hit)', () => {
        assert.throws(
            () => response({ error: { type: 'DynamoDB:ConditionalCheckFailedException', message: 'x' } }),
            /PUBLIC_ORDER_LIMIT_EXCEEDED: This campaign has reached its public order limit/
        );
    });

    it('propagates any other datastore error', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('returns the updated item on success', () => {
        const result = { campaignId: 'c1', publicOrderCount: 1 };
        assert.strictEqual(response({ result }), result);
    });
});
