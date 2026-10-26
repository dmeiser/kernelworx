import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lookup_account_by_email_fn.js';

describe('lookup_account_by_email_fn request', () => {
    it('queries email-index GSI with targetAccountEmail from input and limit 1', () => {
        const ctx = {
            args: {
                input: {
                    targetAccountEmail: 'seller@example.com',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'email-index');
        assert.strictEqual(result.limit, 1);
        assert.strictEqual(result.query.expression, 'email = :email');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':email': 'seller@example.com',
        });
    });
});

describe('lookup_account_by_email_fn response', () => {
    it('throws INVALID_INPUT when items is missing or empty', () => {
        assert.throws(
            () => response({ result: {}, stash: {} }),
            /INVALID_INPUT: Share recipient not found or not eligible/
        );

        assert.throws(
            () => response({ result: { items: [] }, stash: {} }),
            /INVALID_INPUT: Share recipient not found or not eligible/
        );
    });

    it('stashes targetAccountId and returns the account on success', () => {
        const account = {
            accountId: 'ACCOUNT#acc-123',
            email: 'seller@example.com',
            name: 'Test Account',
        };
        const ctx = {
            stash: {},
            result: {
                items: [account],
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, account);
        assert.strictEqual(ctx.stash.targetAccountId, 'ACCOUNT#acc-123');
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'Query failed',
                type: 'INTERNAL_ERROR',
            },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Query failed/
        );
    });
});
