import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_catalog_usage_fn.js';

describe('check_catalog_usage_fn request', () => {
    it('queries catalogId-index with CATALOG# prefix when catalogId is raw', () => {
        const ctx = {
            args: { catalogId: 'cat-123' },
            prev: { result: { catalogId: 'CATALOG#cat-123' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'catalogId-index');
        assert.strictEqual(result.query.expression, 'catalogId = :catalogId');
        assert.strictEqual(result.query.expressionValues[':catalogId'], 'CATALOG#cat-123');
        assert.strictEqual(result.limit, 5);
    });

    it('queries catalogId-index without double prefixing when catalogId already has CATALOG#', () => {
        const ctx = {
            args: { catalogId: 'CATALOG#cat-456' },
            prev: { result: { catalogId: 'CATALOG#cat-456' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.query.expressionValues[':catalogId'], 'CATALOG#cat-456');
    });
});

describe('check_catalog_usage_fn response', () => {
    it('passes through previous result when no campaigns reference the catalog', () => {
        const catalog = { catalogId: 'CATALOG#cat-123', catalogName: 'Spring Popcorn' };
        const ctx = {
            prev: { result: catalog },
            result: { items: [] },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
    });

    it('passes through previous result when result items is undefined', () => {
        const catalog = { catalogId: 'CATALOG#cat-123' };
        const ctx = {
            prev: { result: catalog },
            result: {},
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
    });

    it('throws CatalogInUse error when one campaign references the catalog', () => {
        const ctx = {
            prev: { result: { catalogId: 'CATALOG#cat-123' } },
            result: {
                items: [
                    { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat-123' },
                ],
            },
        };

        assert.throws(
            () => response(ctx),
            /CatalogInUse: Cannot delete catalog: 1 campaign\(s\) are using it\. Please update or delete those campaigns first\./
        );
    });

    it('throws CatalogInUse error with plural count when multiple campaigns reference the catalog', () => {
        const ctx = {
            prev: { result: { catalogId: 'CATALOG#cat-123' } },
            result: {
                items: [
                    { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat-123' },
                    { campaignId: 'CAMPAIGN#c2', catalogId: 'CATALOG#cat-123' },
                    { campaignId: 'CAMPAIGN#c3', catalogId: 'CATALOG#cat-123' },
                ],
            },
        };

        assert.throws(
            () => response(ctx),
            /CatalogInUse: Cannot delete catalog: 3 campaign\(s\) are using it\. Please update or delete those campaigns first\./
        );
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            prev: { result: { catalogId: 'CATALOG#cat-123' } },
            error: { message: 'DynamoDB failure', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: DynamoDB failure/
        );
    });
});
