import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './throttle_public_order_create_fn.js';

// The test harness mocks util.time.nowEpochSeconds() to 1704067200
// (2024-01-01T00:00:00Z), which is already window-aligned, so the window key
// and TTL below are exact.

describe('throttle_public_order_create request', () => {
    it('refuses a missing stash token as NOT_FOUND (wiring fault)', () => {
        assert.throws(() => request({ stash: {} }), /NOT_FOUND: Order could not be placed/);
    });

    it('issues a blind atomic UpdateItem keyed by token and window with the count condition', () => {
        const req = request({ stash: { publicOrderToken: 'tok123' } });
        assert.deepStrictEqual(req, {
            operation: 'UpdateItem',
            key: { key: 'tok123#1704067200' },
            update: {
                expression: 'ADD #n :one SET #expiresAt = :expiresAt',
                expressionNames: { '#n': 'n', '#expiresAt': 'expiresAt' },
                expressionValues: { ':one': 1, ':expiresAt': 1704067320 },
            },
            condition: {
                expression: 'attribute_not_exists(#n) OR #n < :limit',
                expressionValues: { ':limit': 5 },
            },
        });
    });
});

describe('throttle_public_order_create response', () => {
    it('allows the create when the condition passes', () => {
        assert.deepStrictEqual(response({}), { allowed: true });
    });

    it('rejects over-window creates with the campaign-cap limit error shape', () => {
        assert.throws(
            () => response({ error: { message: 'The conditional request failed', type: 'DynamoDB:ConditionalCheckFailedException' } }),
            /PUBLIC_ORDER_LIMIT_EXCEEDED: This campaign has reached its public order limit/
        );
    });
});
