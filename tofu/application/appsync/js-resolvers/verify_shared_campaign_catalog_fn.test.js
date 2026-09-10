import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_shared_campaign_catalog_fn.js';

describe('verify_shared_campaign_catalog_fn request', () => {
    it('requests the shared campaign catalog with consistent read', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#cat-1' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('prefixes unprefixed catalogIds', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'cat-1' } },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-1' });
    });

    it('returns NOOP GetItem when no shared campaign is stashed', () => {
        const ctx = { stash: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'NOOP' });
    });

    it('returns NOOP GetItem when shared campaign has no catalogId', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1' } },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { catalogId: 'NOOP' });
    });
});

describe('verify_shared_campaign_catalog_fn response', () => {
    it('returns the catalog when it exists and is not deleted', () => {
        const catalog = { catalogId: 'CATALOG#cat-1' };
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#cat-1' } },
            result: catalog,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
    });

    it('throws INVALID_INPUT when the catalog is missing', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#gone' } },
            result: null,
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Shared Campaign CODE-1 is no longer available/
        );
    });

    it('throws INVALID_INPUT when the catalog is soft-deleted', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#gone' } },
            result: { catalogId: 'CATALOG#gone', isDeleted: true },
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Shared Campaign CODE-1 is no longer available/
        );
    });

    it('returns null when no shared campaign is stashed', () => {
        const ctx = { stash: {}, result: null };

        const result = response(ctx);

        assert.strictEqual(result, null);
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#cat-1' } },
            error: { message: 'DynamoDB timeout', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: DynamoDB timeout/
        );
    });
});