import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_campaign_for_delete_fn.js';

describe('lookup_campaign_for_delete_fn request', () => {
    it('queries campaignId-index GSI with campaignId and consistentRead false', () => {
        const ctx = {
            args: {
                campaignId: 'CAMPAIGN#c1',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'campaignId-index');
        assert.strictEqual(result.consistentRead, false);
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'CAMPAIGN#c1',
        });
    });

    // #717: the GSI key is the DB form, so an unprefixed campaignId matched nothing
    // and deleteCampaign silently took the idempotent no-op path.
    it('normalizes an unprefixed campaignId to the DB form', () => {
        const result = request({ args: { campaignId: 'c1' } });

        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'CAMPAIGN#c1',
        });
    });
});

describe('lookup_campaign_for_delete_fn response', () => {
    it('handles missing items idempotently by stashing null and returning null', () => {
        const ctxMissingItems = { result: {}, stash: {} };
        const resultMissing = response(ctxMissingItems);
        assert.strictEqual(resultMissing, null);
        assert.strictEqual(ctxMissingItems.stash.campaign, null);

        const ctxEmptyItems = { result: { items: [] }, stash: {} };
        const resultEmpty = response(ctxEmptyItems);
        assert.strictEqual(resultEmpty, null);
        assert.strictEqual(ctxEmptyItems.stash.campaign, null);
    });

    it('stashes campaign and returns it when found', () => {
        const campaign = {
            campaignId: 'CAMPAIGN#c1',
            profileId: 'PROFILE#p1',
            campaignName: 'Spring Fundraiser',
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
                message: 'Lookup failed',
                type: 'INTERNAL_ERROR',
            },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Lookup failed/
        );
    });
});
