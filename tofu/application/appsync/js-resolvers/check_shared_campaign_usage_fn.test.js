import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './check_shared_campaign_usage_fn.js';

describe('check_shared_campaign_usage_fn request', () => {
    it('queries catalogId-index with CATALOG# prefix when catalogId is raw', () => {
        const ctx = {
            args: { catalogId: 'catalog-abc' },
            prev: { result: { catalogId: 'CATALOG#catalog-abc' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'catalogId-index');
        assert.strictEqual(result.query.expression, 'catalogId = :catalogId');
        assert.strictEqual(result.query.expressionValues[':catalogId'], 'CATALOG#catalog-abc');
        assert.strictEqual(result.limit, 5);
    });

    it('queries catalogId-index without double prefixing when catalogId already has CATALOG#', () => {
        const ctx = {
            args: { catalogId: 'CATALOG#catalog-xyz' },
            prev: { result: { catalogId: 'CATALOG#catalog-xyz' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.query.expressionValues[':catalogId'], 'CATALOG#catalog-xyz');
    });
});

describe('check_shared_campaign_usage_fn response', () => {
    it('passes through previous result when no shared campaigns reference the catalog', () => {
        const catalog = { catalogId: 'CATALOG#catalog-abc' };
        const ctx = {
            prev: { result: catalog },
            result: { items: [] },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
    });

    it('throws CatalogInUse error when shared campaigns reference the catalog', () => {
        const ctx = {
            prev: { result: { catalogId: 'CATALOG#catalog-abc' } },
            result: {
                items: [
                    { sharedCampaignCode: 'PACK1-FALL-IL-25', catalogId: 'CATALOG#catalog-abc' },
                ],
            },
        };

        assert.throws(
            () => response(ctx),
            /Cannot delete catalog: 1 shared campaign\(s\) are referencing it/
        );
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            prev: { result: { catalogId: 'CATALOG#catalog-abc' } },
            error: { message: 'DynamoDB timeout', type: 'InternalServerError' },
        };

        assert.throws(
            () => response(ctx),
            /InternalServerError: DynamoDB timeout/
        );
    });
});
