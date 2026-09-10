import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './lambda_unit_resolver.js';

describe('lambda_unit_resolver request', () => {
    it('invokes the Lambda with the full AppSync context as payload', () => {
        const ctx = {
            arguments: { campaignId: 'CAMPAIGN#c1' },
            identity: { sub: 'user-123' },
            info: { fieldName: 'listMyShares' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.deepStrictEqual(result.payload, ctx);
    });
});

describe('lambda_unit_resolver response', () => {
    it('surfaces structured handler errors with their typed error code', () => {
        const ctx = {
            result: { __isError: true, errorCode: 'NOT_FOUND', message: 'Campaign not found' },
            error: null,
        };

        assert.throws(
            () => response(ctx),
            (err) => {
                assert.strictEqual(err.message, 'NOT_FOUND: Campaign not found');
                assert.deepStrictEqual(err.errorInfo, { errorCode: 'NOT_FOUND' });
                return true;
            }
        );
    });

    it('surfaces data source errors', () => {
        const ctx = {
            result: null,
            error: { message: 'Lambda timed out', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            (err) => err.message === 'INTERNAL_ERROR: Lambda timed out'
        );
    });

    it('returns the handler result on success', () => {
        const ctx = { result: ['CATALOG#c1', 'CATALOG#c2'], error: null };

        const result = response(ctx);

        assert.deepStrictEqual(result, ['CATALOG#c1', 'CATALOG#c2']);
    });
});
