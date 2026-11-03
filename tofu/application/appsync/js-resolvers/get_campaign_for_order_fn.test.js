import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_campaign_for_order_fn.js';

describe('get_campaign_for_order_fn request', () => {
    it('queries campaignId-index GSI with campaignId from input and limit 1', () => {
        const ctx = {
            args: {
                input: { campaignId: 'CAMPAIGN#c1' },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'campaignId-index');
        assert.strictEqual(result.limit, 1);
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.strictEqual(result.query.expressionValues[':campaignId'], 'CAMPAIGN#c1');
    });

    // #717: Step 1 of createOrder queried the GSI with the raw input, so an
    // unprefixed campaignId failed with NOT_FOUND before create_order_fn (which
    // does normalize) was ever reached.
    it('normalizes an unprefixed campaignId to the DB form', () => {
        const result = request({ args: { input: { campaignId: 'c1' } } });

        assert.strictEqual(result.index, 'campaignId-index');
        assert.strictEqual(result.query.expressionValues[':campaignId'], 'CAMPAIGN#c1');
    });
});

describe('get_campaign_for_order_fn response', () => {
    it('throws NOT_FOUND when items is empty or missing', () => {
        assert.throws(
            () => response({ result: { items: [] }, stash: {} }),
            /NOT_FOUND: Campaign not found/
        );

        assert.throws(
            () => response({ result: {}, stash: {} }),
            /NOT_FOUND: Campaign not found/
        );
    });

    it('throws INVALID_INPUT when campaign has no catalogId', () => {
        const ctx = {
            stash: {},
            result: {
                items: [{ campaignId: 'CAMPAIGN#c1', campaignName: 'Fall Popcorn' }],
            },
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Campaign has no catalog assigned/
        );
    });

    it('defaults null or undefined isActive to true and normalizes raw catalogId', () => {
        const ctx = {
            stash: {},
            result: {
                items: [
                    {
                        campaignId: 'CAMPAIGN#c1',
                        catalogId: 'cat-123',
                        isActive: null,
                    },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.isActive, true);
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#cat-123');
        assert.deepStrictEqual(ctx.stash.campaign, result);
    });

    it('preserves catalogId that already carries CATALOG# prefix', () => {
        const ctx = {
            stash: {},
            result: {
                items: [
                    {
                        campaignId: 'CAMPAIGN#c1',
                        catalogId: 'CATALOG#cat-456',
                        isActive: true,
                    },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.isActive, true);
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#cat-456');
    });

    it('preserves explicit isActive false on campaign', () => {
        const ctx = {
            stash: {},
            result: {
                items: [
                    {
                        campaignId: 'CAMPAIGN#c1',
                        catalogId: 'CATALOG#cat-456',
                        isActive: false,
                    },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.isActive, false);
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: { message: 'Query failed', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Query failed/
        );
    });
});
