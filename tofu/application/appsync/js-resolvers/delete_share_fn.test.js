import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_share_fn.js';

describe('delete_share_fn request', () => {
    it('constructs DeleteItem with normalized keys and ownerAccountId condition', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'p-123',
                    targetAccountId: 'user-456'
                }
            },
            identity: {
                sub: 'owner-789'
            }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'DeleteItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p-123',
            targetAccountId: 'ACCOUNT#user-456'
        });
        assert.deepStrictEqual(result.condition, {
            expression: 'ownerAccountId = :caller',
            expressionValues: {
                ':caller': 'ACCOUNT#owner-789'
            }
        });
    });

    it('preserves prefixes if already present in args and identity', () => {
        const ctx = {
            args: {
                input: {
                    profileId: 'PROFILE#p-123',
                    targetAccountId: 'ACCOUNT#user-456'
                }
            },
            identity: {
                sub: 'ACCOUNT#owner-789'
            }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'DeleteItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p-123',
            targetAccountId: 'ACCOUNT#user-456'
        });
        assert.deepStrictEqual(result.condition, {
            expression: 'ownerAccountId = :caller',
            expressionValues: {
                ':caller': 'ACCOUNT#owner-789'
            }
        });
    });
});

describe('delete_share_fn response', () => {
    it('returns true on successful deletion', () => {
        const ctx = {
            error: null
        };

        const result = response(ctx);
        assert.strictEqual(result, true);
    });

    it('throws Unauthorized error on ConditionalCheckFailedException', () => {
        const ctx = {
            error: {
                type: 'DynamoDB:ConditionalCheckFailedException',
                message: 'The conditional request failed'
            }
        };

        assert.throws(
            () => response(ctx),
            /Unauthorized: Not authorized to revoke this share or share not found/
        );
    });

    it('throws original error for other error types', () => {
        const ctx = {
            error: {
                type: 'DynamoDB:InternalServerError',
                message: 'Internal error occurred'
            }
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: Internal error occurred/
        );
    });
});
