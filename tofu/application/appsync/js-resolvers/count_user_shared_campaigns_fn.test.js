import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './count_user_shared_campaigns_fn.js';

describe('count_user_shared_campaigns_fn request', () => {
    it('queries GSI1 with ACCOUNT# prefix when sub is raw', () => {
        const ctx = {
            identity: { sub: 'user-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'GSI1');
        assert.strictEqual(result.select, 'COUNT');
        assert.strictEqual(result.query.expression, 'createdBy = :createdBy');
        assert.strictEqual(result.query.expressionValues[':createdBy'], 'ACCOUNT#user-123');
    });

    it('queries GSI1 without double prefixing when sub already has ACCOUNT#', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-456' },
        };

        const result = request(ctx);

        assert.strictEqual(result.query.expressionValues[':createdBy'], 'ACCOUNT#user-456');
    });
});

describe('count_user_shared_campaigns_fn response', () => {
    it('returns count and stashes sharedCampaignCount when count is below limit', () => {
        const ctx = {
            stash: {},
            result: { count: 12 },
        };

        const result = response(ctx);

        assert.strictEqual(result, 12);
        assert.strictEqual(ctx.stash.sharedCampaignCount, 12);
    });

    it('defaults count to 0 when ctx.result.count is undefined', () => {
        const ctx = {
            stash: {},
            result: {},
        };

        const result = response(ctx);

        assert.strictEqual(result, 0);
        assert.strictEqual(ctx.stash.sharedCampaignCount, 0);
    });

    it('allows count of 49 (one below maximum)', () => {
        const ctx = {
            stash: {},
            result: { count: 49 },
        };

        const result = response(ctx);

        assert.strictEqual(result, 49);
        assert.strictEqual(ctx.stash.sharedCampaignCount, 49);
    });

    it('throws RateLimitExceeded error when count reaches 50', () => {
        const ctx = {
            stash: {},
            result: { count: 50 },
        };

        assert.throws(
            () => response(ctx),
            /RateLimitExceeded: Rate limit exceeded: Maximum 50 campaign shared campaigns per user/
        );
        assert.strictEqual(ctx.stash.sharedCampaignCount, undefined);
    });

    it('throws RateLimitExceeded error when count exceeds 50', () => {
        const ctx = {
            stash: {},
            result: { count: 55 },
        };

        assert.throws(
            () => response(ctx),
            /RateLimitExceeded: Rate limit exceeded: Maximum 50 campaign shared campaigns per user/
        );
        assert.strictEqual(ctx.stash.sharedCampaignCount, undefined);
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            stash: {},
            error: { message: 'Service unavailable', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Service unavailable/
        );
    });
});
