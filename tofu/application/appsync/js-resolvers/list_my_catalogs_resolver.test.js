import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './list_my_catalogs_resolver.js';

describe('list_my_catalogs_resolver request', () => {
    it('queries the owner GSI with the normalized ACCOUNT# key and a soft-delete filter', () => {
        const ctx = { identity: { sub: 'user-123' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'ownerAccountId-index');
        assert.deepStrictEqual(result.query, {
            expression: 'ownerAccountId = :ownerAccountId',
            expressionValues: { ':ownerAccountId': 'ACCOUNT#user-123' },
        });
        assert.deepStrictEqual(result.filter, {
            expression: 'attribute_not_exists(isDeleted) OR isDeleted = :false',
            expressionValues: { ':false': false },
        });
    });

    it('keeps an already-prefixed sub as one prefix', () => {
        const ctx = { identity: { sub: 'ACCOUNT#user-123' } };

        assert.strictEqual(request(ctx).query.expressionValues[':ownerAccountId'], 'ACCOUNT#user-123');
    });

    it('falls back to the bare ACCOUNT# placeholder when the sub is missing', () => {
        // The placeholder matches no real partition key, so a missing claim
        // yields an empty page rather than another account's catalogs.
        const ctx = { identity: {} };

        assert.strictEqual(request(ctx).query.expressionValues[':ownerAccountId'], 'ACCOUNT#');
    });
});

describe('list_my_catalogs_resolver response', () => {
    it('returns the queried items', () => {
        const items = [{ catalogId: 'CATALOG#c-1' }, { catalogId: 'CATALOG#c-2' }];

        assert.deepStrictEqual(response({ result: { items } }), items);
    });

    it('returns an empty list when the query produced no items key', () => {
        for (const result of [{}, { items: null }, { items: [] }]) {
            assert.deepStrictEqual(response({ result }), []);
        }
    });

    it('propagates a DynamoDB error unchanged', () => {
        const ctx = { error: { message: 'Throttling', type: 'RESOURCE_BUSY' } };

        assert.throws(() => response(ctx), /RESOURCE_BUSY: Throttling/);
    });
});
