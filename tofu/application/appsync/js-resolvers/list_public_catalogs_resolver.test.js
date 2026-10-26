import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './list_public_catalogs_resolver.js';

describe('list_public_catalogs_resolver request', () => {
    it('queries the public GSI on the string flag, newest first, filtered to admin-managed', () => {
        const result = request({ args: {}, identity: { sub: 'user-123' } });

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'isPublic-createdAt-index');
        assert.deepStrictEqual(result.query, {
            expression: 'isPublicStr = :isPublicStr',
            expressionValues: { ':isPublicStr': 'true' },
        });
        assert.deepStrictEqual(result.filter, {
            expression: '(attribute_not_exists(isDeleted) OR isDeleted = :false) AND catalogType = :adminManaged',
            expressionValues: { ':false': false, ':adminManaged': 'ADMIN_MANAGED' },
        });
        assert.strictEqual(result.scanIndexForward, false);
    });

    it('ignores caller arguments, so no client input widens the public scope', () => {
        const plain = request({ args: {}, identity: { sub: 'user-123' } });
        const injected = request({
            args: { catalogType: 'USER_OWNED', ownerAccountId: 'ACCOUNT#someone-else' },
            identity: { sub: 'user-123' },
        });

        assert.deepStrictEqual(injected, plain);
    });
});

describe('list_public_catalogs_resolver response', () => {
    it('returns the queried items', () => {
        const items = [{ catalogId: 'CATALOG#public-1' }];

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
