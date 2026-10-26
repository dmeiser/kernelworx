import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_campaign_for_orders_fn.js';

describe('lookup_campaign_for_orders_fn request', () => {
    it('queries campaignId-index GSI with campaignId and limit 1', () => {
        const ctx = {
            args: {
                campaignId: 'CAMPAIGN#c1',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'campaignId-index');
        assert.strictEqual(result.limit, 1);
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'CAMPAIGN#c1',
        });
    });
});

describe('lookup_campaign_for_orders_fn response', () => {
    it('flags campaignNotFound and unauthorized when items is missing or empty', () => {
        const ctxMissing = { result: {}, stash: {} };
        const resultMissing = response(ctxMissing);
        assert.strictEqual(resultMissing, null);
        assert.strictEqual(ctxMissing.stash.campaignNotFound, true);
        assert.strictEqual(ctxMissing.stash.authorized, false);

        const ctxEmpty = { result: { items: [] }, stash: {} };
        const resultEmpty = response(ctxEmpty);
        assert.strictEqual(resultEmpty, null);
        assert.strictEqual(ctxEmpty.stash.campaignNotFound, true);
        assert.strictEqual(ctxEmpty.stash.authorized, false);
    });

    it('stashes campaign and profileId, and returns campaign when found', () => {
        const campaign = {
            campaignId: 'CAMPAIGN#c1',
            profileId: 'PROFILE#p1',
            campaignName: 'Summer Camp Campaign',
        };
        const ctx = {
            stash: {},
            result: {
                items: [campaign],
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, campaign);
        assert.deepStrictEqual(ctx.stash.campaign, campaign);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#p1');
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'Query failed',
                type: 'INTERNAL_ERROR',
            },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Query failed/
        );
    });
});
