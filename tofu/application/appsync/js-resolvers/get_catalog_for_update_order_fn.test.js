import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_catalog_for_update_order_fn.js';

describe('get_catalog_for_update_order_fn request', () => {
    it('sets skipCatalog true and returns NOOP query when lineItems is omitted', () => {
        const ctx = {
            args: {
                input: { orderNotes: 'Please deliver after 5pm' },
            },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(ctx.stash.skipCatalog, true);
        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'campaignId-index');
        assert.strictEqual(result.query.expressionValues[':campaignId'], 'NOOP');
        assert.strictEqual(result.limit, 1);
    });

    it('sets skipCatalog true when lineItems is null or undefined', () => {
        const ctx = {
            args: {
                input: { lineItems: null },
            },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(ctx.stash.skipCatalog, true);
        assert.strictEqual(result.query.expressionValues[':campaignId'], 'NOOP');
    });

    it('queries campaignId-index with campaignId from order when lineItems is present', () => {
        const ctx = {
            args: {
                input: {
                    lineItems: [{ productId: 'PROD#p1', quantity: 2 }],
                },
            },
            stash: {
                order: { campaignId: 'CAMPAIGN#c123' },
            },
        };

        const result = request(ctx);

        assert.strictEqual(ctx.stash.skipCatalog, undefined);
        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'campaignId-index');
        assert.strictEqual(result.limit, 1);
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.strictEqual(result.query.expressionValues[':campaignId'], 'CAMPAIGN#c123');
    });
});

describe('get_catalog_for_update_order_fn response', () => {
    it('returns null when skipCatalog is true in stash', () => {
        const ctx = {
            stash: { skipCatalog: true },
            result: null,
        };

        const result = response(ctx);

        assert.strictEqual(result, null);
    });

    it('throws NOT_FOUND when items is empty or missing', () => {
        assert.throws(
            () => response({ stash: {}, result: { items: [] } }),
            /NOT_FOUND: Campaign not found/
        );

        assert.throws(
            () => response({ stash: {}, result: {} }),
            /NOT_FOUND: Campaign not found/
        );
    });

    it('throws INVALID_INPUT when campaign has no catalogId', () => {
        const ctx = {
            stash: {},
            result: {
                items: [{ campaignId: 'CAMPAIGN#c123' }],
            },
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Campaign does not have a catalog assigned/
        );
    });

    it('stashes catalogId in stash and returns campaign on success', () => {
        const campaign = {
            campaignId: 'CAMPAIGN#c123',
            catalogId: 'CATALOG#cat-1',
            campaignName: 'Spring Popcorn',
        };
        const ctx = {
            stash: {},
            result: {
                items: [campaign],
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, campaign);
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#cat-1');
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: { message: 'Database error', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Database error/
        );
    });
});
