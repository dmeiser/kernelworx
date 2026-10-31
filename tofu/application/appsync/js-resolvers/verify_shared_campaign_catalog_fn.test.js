import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_shared_campaign_catalog_fn.js';

describe('verify_shared_campaign_catalog_fn request', () => {
    it('requests the shared campaign catalog with consistent read', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#cat-1' } },
            args: { input: {} },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('prefixes unprefixed catalogIds', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'cat-1' } },
            args: { input: {} },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-1' });
    });

    it('returns NOOP GetItem when no shared campaign and no input catalogId', () => {
        const ctx = { stash: {}, args: { input: {} } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'NOOP' });
    });

    it('returns NOOP GetItem when shared campaign has no catalogId', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1' } },
            args: { input: {} },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { catalogId: 'NOOP' });
    });

    it('fetches input.catalogId on the direct path (no shared campaign) (#706)', () => {
        const ctx = {
            stash: {},
            args: { input: { catalogId: 'CATALOG#direct-1' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#direct-1' });
        assert.strictEqual(result.consistentRead, true);
    });
});

describe('verify_shared_campaign_catalog_fn response', () => {
    it('returns the catalog when it exists and is not deleted', () => {
        const catalog = { catalogId: 'CATALOG#cat-1', ownerAccountId: 'ACCOUNT#creator-1' };
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#cat-1', createdBy: 'ACCOUNT#creator-1' } },
            args: { input: {} },
            result: catalog,
            identity: { sub: 'joiner-1' },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, catalog);
    });

    it('throws INVALID_INPUT when the catalog is missing', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#gone', createdBy: 'ACCOUNT#creator-1' } },
            args: { input: {} },
            result: null,
            identity: { sub: 'joiner-1' },
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Shared Campaign CODE-1 is no longer available/
        );
    });

    it('throws INVALID_INPUT when the catalog is soft-deleted', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#gone', createdBy: 'ACCOUNT#creator-1' } },
            args: { input: {} },
            result: { catalogId: 'CATALOG#gone', isDeleted: true },
            identity: { sub: 'joiner-1' },
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Shared Campaign CODE-1 is no longer available/
        );
    });

    it('throws INVALID_INPUT when the catalog is no longer accessible to the creator (#706)', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#cat-1', createdBy: 'ACCOUNT#creator-1' } },
            args: { input: {} },
            result: { catalogId: 'CATALOG#cat-1', ownerAccountId: 'ACCOUNT#someone-else' },
            identity: { sub: 'joiner-1' },
        };

        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Shared Campaign CODE-1 is no longer available/
        );
    });

    it('returns null when no shared campaign and no input catalogId', () => {
        const ctx = { stash: {}, args: { input: {} }, result: null, identity: { sub: 'user-1' } };

        const result = response(ctx);

        assert.strictEqual(result, null);
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            stash: { sharedCampaign: { sharedCampaignCode: 'CODE-1', catalogId: 'CATALOG#cat-1', createdBy: 'ACCOUNT#creator-1' } },
            args: { input: {} },
            error: { message: 'DynamoDB timeout', type: 'INTERNAL_ERROR' },
            identity: { sub: 'joiner-1' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: DynamoDB timeout/
        );
    });
});