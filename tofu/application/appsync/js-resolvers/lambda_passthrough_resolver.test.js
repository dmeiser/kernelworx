import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lambda_passthrough_resolver.js';

describe('lambda_passthrough_resolver request', () => {
    it('invokes Lambda with arguments, identity, info, stash, and requestId', () => {
        const ctx = {
            arguments: { limit: 10 },
            identity: { sub: 'user-123' },
            info: { fieldName: 'adminListUsers', parentTypeName: 'Query' },
            stash: {},
            request: { headers: { 'x-amzn-requestid': 'req-abc-123' } },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.deepStrictEqual(result.payload.arguments, { limit: 10 });
        assert.deepStrictEqual(result.payload.identity, { sub: 'user-123' });
        assert.deepStrictEqual(result.payload.info, { fieldName: 'adminListUsers', parentTypeName: 'Query' });
        assert.deepStrictEqual(result.payload.stash, {});
        assert.strictEqual(result.payload.requestId, 'req-abc-123');
    });

    it('passes requestId as undefined when ctx.request is absent (#748)', () => {
        const result = request({ arguments: {}, identity: {}, stash: {} });

        assert.strictEqual(result.payload.requestId, undefined);
        assert.strictEqual('requestId' in result.payload, true);
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

    it('does not fabricate a prev.result payload (#748)', () => {
        const result = request({
            arguments: {},
            identity: {},
            stash: { profileOwner: 'ACCOUNT#1', customPaymentMethods: [{ id: 'pm-1' }] },
        });

        assert.strictEqual('prev' in result.payload, false);
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
