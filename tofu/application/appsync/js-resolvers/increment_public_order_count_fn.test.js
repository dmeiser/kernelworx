import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './increment_public_order_count_fn.js';

// #679 write slice, spec §10.1/§4.3: the cap gate. The bound rides the
// ConditionExpression of an atomic ADD - a read-side pre-check alone overshoots.

function ctxWith(stash) {
    return { stash: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', ...(stash || {}) }, result: null, error: null };
}

describe('increment_public_order_count_fn request', () => {
    it('ADDs one to publicOrderCount on the anchor campaign row', () => {
        const result = request(ctxWith());

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(result.update.expression, 'ADD #publicOrderCount :one');
        assert.deepStrictEqual(result.update.expressionValues, { ':one': 1 });
    });

    it('carries the cap inside the condition expression', () => {
        const condition = request(ctxWith()).condition;

        assert.strictEqual(
            condition.expression,
            'attribute_exists(campaignId) AND (attribute_not_exists(#publicOrderCount) OR #publicOrderCount < :cap)'
        );
        assert.deepStrictEqual(condition.expressionValues, { ':cap': 500 });
        assert.deepStrictEqual(condition.expressionNames, { '#publicOrderCount': 'publicOrderCount' });
    });

    it('escapes the counter name in both expressions', () => {
        const result = request(ctxWith());
        assert.deepStrictEqual(result.update.expressionNames, { '#publicOrderCount': 'publicOrderCount' });
        assert.ok(!result.update.expression.includes(' publicOrderCount'));
    });

    it('refuses to write when the stash is missing a key', () => {
        assert.throws(
            () => request(ctxWith({ profileId: null })),
            /PUBLIC_ORDER_LIMIT_EXCEEDED: This campaign has reached its public order limit/
        );
    });
});

describe('increment_public_order_count_fn response', () => {
    it('maps a condition failure at the cap to the non-retryable limit code', () => {
        const ctx = ctxWith();
        ctx.error = { type: 'DynamoDB:ConditionalCheckFailedException', message: 'conditional write failed' };

        assert.throws(() => response(ctx), /PUBLIC_ORDER_LIMIT_EXCEEDED: This campaign has reached its public order limit/);
    });

    it('maps the bare ConditionalCheckFailed spelling the same way', () => {
        const ctx = ctxWith();
        ctx.error = { type: 'ConditionalCheckFailedException', message: 'conditional write failed' };
        assert.throws(() => response(ctx), /PUBLIC_ORDER_LIMIT_EXCEEDED/);
    });

    it('maps a message-only ConditionalCheckFailed spelling the same way', () => {
        const ctx = ctxWith();
        ctx.error = { type: 'DynamoDB', message: 'ConditionalCheckFailedException: bound exceeded' };
        assert.throws(() => response(ctx), /PUBLIC_ORDER_LIMIT_EXCEEDED/);
    });

    it('surfaces any other datastore error unchanged', () => {
        const ctx = ctxWith();
        ctx.error = { type: 'DynamoDB:ThrottlingException', message: 'slow down' };
        assert.throws(() => response(ctx), /ThrottlingException: slow down/);
    });

    it('returns the incremented item on success', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', publicOrderCount: 3 };
        assert.deepStrictEqual(response(ctx), { campaignId: 'CAMPAIGN#c1', publicOrderCount: 3 });
    });
});
