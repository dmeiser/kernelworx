import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_campaign_fn.js';

describe('query_campaign_fn request', () => {
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

    // #717: the GSI key is the DB form, so an unprefixed campaignId made getCampaign
    // report a campaign that exists as not found.
    it('normalizes an unprefixed campaignId to the DB form', () => {
        const result = request({ args: { campaignId: 'c1' } });

        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'CAMPAIGN#c1',
        });
    });
});

describe('query_campaign_fn response', () => {
    it('stashes campaignNotFound and returns null when result is null or items is empty', () => {
        const ctxNullResult = { result: null, stash: {} };
        const resultNull = response(ctxNullResult);
        assert.strictEqual(resultNull, null);
        assert.strictEqual(ctxNullResult.stash.campaignNotFound, true);

        const ctxMissingItems = { result: {}, stash: {} };
        const resultMissing = response(ctxMissingItems);
        assert.strictEqual(resultMissing, null);
        assert.strictEqual(ctxMissingItems.stash.campaignNotFound, true);

        const ctxEmptyItems = { result: { items: [] }, stash: {} };
        const resultEmpty = response(ctxEmptyItems);
        assert.strictEqual(resultEmpty, null);
        assert.strictEqual(ctxEmptyItems.stash.campaignNotFound, true);
    });

    it('stashes campaign and returns it on success', () => {
        const campaign = {
            campaignId: 'CAMPAIGN#c1',
            profileId: 'PROFILE#p1',
            campaignName: 'Winter Popcorn',
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
