import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_campaign_fn.js';

describe('lookup_campaign_fn request', () => {
    it('queries campaignId-index GSI using args.campaignId', () => {
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

    it('queries campaignId-index GSI using args.input.campaignId fallback', () => {
        const ctx = {
            args: {
                input: {
                    campaignId: 'CAMPAIGN#c2',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'campaignId-index');
        assert.strictEqual(result.consistentRead, false);
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'CAMPAIGN#c2',
        });
    });

    // #717: the GSI key is the DB form, so an unprefixed campaignId matched nothing.
    it('normalizes an unprefixed campaignId to the DB form', () => {
        const result = request({ args: { campaignId: 'c1' } });

        assert.deepStrictEqual(result.query.expressionValues, {
            ':campaignId': 'CAMPAIGN#c1',
        });
    });
});

describe('lookup_campaign_fn response', () => {
    it('throws NOT_FOUND when items is missing or empty', () => {
        assert.throws(
            () => response({ result: {}, stash: {} }),
            /NOT_FOUND: Campaign not found/
        );

        assert.throws(
            () => response({ result: { items: [] }, stash: {} }),
            /NOT_FOUND: Campaign not found/
        );
    });

    it('stashes campaign and returns it on success', () => {
        const campaign = {
            campaignId: 'CAMPAIGN#c1',
            profileId: 'PROFILE#p1',
            campaignName: 'Popcorn Sale',
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
                message: 'DynamoDB query failed',
                type: 'INTERNAL_ERROR',
            },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: DynamoDB query failed/
        );
    });
});
