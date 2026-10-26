import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './ensure_my_account_exists_fn.js';

describe('ensure_my_account_exists_fn request', () => {
    it('returns consistent GetItem request when account was already found in prev step', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            prev: { result: { accountId: 'ACCOUNT#user-123', email: 'test@example.com' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-123' });
    });

    it('does not double-prefix accountId when sub already carries ACCOUNT# prefix', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-456' },
            prev: { result: { accountId: 'ACCOUNT#user-456' } },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-456' });
    });

    it('builds UpdateItem with claims when prev.result is absent', () => {
        const ctx = {
            identity: {
                sub: 'user-789',
                claims: {
                    email: 'scout@example.com',
                    given_name: 'Robin',
                    family_name: 'Hood',
                },
            },
            prev: { result: null },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-789' });
        assert.strictEqual(result.returnValues, 'ALL_NEW');
        assert.ok(result.update.expression.includes('SET #email = if_not_exists(#email, :email)'));
        assert.strictEqual(result.update.expressionValues[':email'], 'scout@example.com');
        assert.strictEqual(result.update.expressionValues[':givenName'], 'Robin');
        assert.strictEqual(result.update.expressionValues[':familyName'], 'Hood');
        assert.strictEqual(result.update.expressionValues[':city'], '');
        assert.strictEqual(result.update.expressionValues[':state'], '');
        assert.strictEqual(result.update.expressionValues[':unitType'], '');
        assert.deepStrictEqual(result.update.expressionValues[':preferences'], { paymentMethods: [] });
        assert.strictEqual(result.update.expressionValues[':createdAt'], '2024-01-01T00:00:00Z');
        assert.strictEqual(result.update.expressionValues[':updatedAt'], '2024-01-01T00:00:00Z');
    });

    it('defaults claims to empty strings when claims object or identity is missing', () => {
        const ctx = {
            identity: { sub: 'user-no-claims' },
            prev: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.update.expressionValues[':email'], '');
        assert.strictEqual(result.update.expressionValues[':givenName'], '');
        assert.strictEqual(result.update.expressionValues[':familyName'], '');
    });

    it('defaults non-string claims to empty strings', () => {
        const ctx = {
            identity: {
                sub: 'user-odd-claims',
                claims: {
                    email: 12345,
                    given_name: null,
                    family_name: false,
                },
            },
            prev: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.update.expressionValues[':email'], '');
        assert.strictEqual(result.update.expressionValues[':givenName'], '');
        assert.strictEqual(result.update.expressionValues[':familyName'], '');
    });
});

describe('ensure_my_account_exists_fn response', () => {
    it('returns prev.result when present', () => {
        const existing = { accountId: 'ACCOUNT#user-123', email: 'test@example.com' };
        const ctx = {
            prev: { result: existing },
            result: null,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, existing);
    });

    it('returns result when prev.result is null', () => {
        const newlyCreated = { accountId: 'ACCOUNT#user-789', email: 'new@example.com' };
        const ctx = {
            prev: { result: null },
            result: newlyCreated,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, newlyCreated);
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            prev: { result: null },
            error: { message: 'ConditionalCheckFailed', type: 'ConditionalCheckFailedException' },
        };

        assert.throws(
            () => response(ctx),
            /ConditionalCheckFailedException: ConditionalCheckFailed/
        );
    });
});
