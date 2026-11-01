import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_catalog_fn.js';

describe('delete_catalog_fn request', () => {
    it('normalizes raw catalogId with CATALOG# prefix and builds UpdateItem', () => {
        const ctx = {
            args: { catalogId: 'cat-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-123' });
        assert.strictEqual(result.update.expression, 'SET isDeleted = :true');
        assert.deepStrictEqual(result.update.expressionValues, { ':true': true });
    });

    it('preserves catalogId that already carries CATALOG# prefix', () => {
        const ctx = {
            args: { catalogId: 'CATALOG#cat-456' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#cat-456' });
        assert.strictEqual(result.update.expression, 'SET isDeleted = :true');
        assert.deepStrictEqual(result.update.expressionValues, { ':true': true });
    });
});

describe('delete_catalog_fn response', () => {
    it('returns true on successful deletion', () => {
        const ctx = {
            error: null,
        };

        const result = response(ctx);

        assert.strictEqual(result, true);
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            error: { message: 'Conditional check failed', type: 'ConditionalCheckFailedException' },
        };

        assert.throws(
            () => response(ctx),
            /ConditionalCheckFailedException: Conditional check failed/
        );
    });
});
