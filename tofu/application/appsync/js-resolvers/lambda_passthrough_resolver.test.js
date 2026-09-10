import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lambda_passthrough_resolver.js';

describe('lambda_passthrough_resolver request', () => {
    it('invokes Lambda with arguments, identity, info, prev, and stash', () => {
        const ctx = {
            arguments: { limit: 10 },
            identity: { sub: 'user-123' },
            info: { fieldName: 'adminListUsers', parentTypeName: 'Query' },
            stash: { profileOwner: 'ACCOUNT#1' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.deepStrictEqual(result.payload.arguments, { limit: 10 });
        assert.deepStrictEqual(result.payload.identity, { sub: 'user-123' });
        assert.deepStrictEqual(result.payload.info, { fieldName: 'adminListUsers', parentTypeName: 'Query' });
        assert.deepStrictEqual(result.payload.stash, { profileOwner: 'ACCOUNT#1' });
    });

    it('passes info through so the admin dispatcher can read info.fieldName', () => {
        const ctx = {
            arguments: {},
            identity: { claims: { 'cognito:groups': ['ADMIN'] } },
            info: { fieldName: 'adminResetUserPassword' },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.payload.info.fieldName, 'adminResetUserPassword');
    });

    it('resolves ownerAccountId from stash.profileOwner', () => {
        const result = request({ arguments: {}, identity: {}, stash: { profileOwner: 'ACCOUNT#1' } });

        assert.strictEqual(result.payload.prev.result.ownerAccountId, 'ACCOUNT#1');
    });

    it('falls back to stash.profile.ownerAccountId then stash.ownerAccountId', () => {
        const fromProfile = request({
            arguments: {},
            identity: {},
            stash: { profile: { ownerAccountId: 'ACCOUNT#2' } },
        });
        assert.strictEqual(fromProfile.payload.prev.result.ownerAccountId, 'ACCOUNT#2');

        const fromStash = request({
            arguments: {},
            identity: {},
            stash: { ownerAccountId: 'ACCOUNT#3' },
        });
        assert.strictEqual(fromStash.payload.prev.result.ownerAccountId, 'ACCOUNT#3');
    });
});

describe('lambda_passthrough_resolver response (#329)', () => {
    it('passes through a successful result', () => {
        const ctx = { result: { users: [] } };

        const result = response(ctx);

        assert.deepStrictEqual(result, { users: [] });
    });

    it('surfaces a structured __isError payload as an error with extensions.errorCode', () => {
        const ctx = {
            result: {
                __isError: true,
                errorCode: 'FORBIDDEN',
                message: 'Admin access required',
            },
        };

        assert.throws(
            () => response(ctx),
            (error) => {
                assert.strictEqual(error.message, 'FORBIDDEN: Admin access required');
                assert.deepStrictEqual(error.errorInfo, { errorCode: 'FORBIDDEN' });
                return true;
            },
        );
    });

    it('keeps the legacy ctx.error path as fallback', () => {
        const ctx = {
            error: { message: 'Lambda failed', type: 'Lambda:Unhandled' },
        };

        assert.throws(
            () => response(ctx),
            (error) => {
                assert.strictEqual(error.message, 'Lambda:Unhandled: Lambda failed');
                return true;
            },
        );
    });
});
