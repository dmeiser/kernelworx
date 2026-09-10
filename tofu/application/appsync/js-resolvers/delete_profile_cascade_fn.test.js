import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_profile_cascade_fn.js';

describe('delete_profile_cascade_fn request', () => {
    it('forwards arguments, identity, and stash to the Lambda', () => {
        const ctx = {
            args: { profileId: 'PROFILE#p1' },
            identity: { sub: 'user-123' },
            stash: { profileOwner: 'user-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.deepStrictEqual(result.payload, {
            arguments: { profileId: 'PROFILE#p1' },
            identity: { sub: 'user-123' },
            stash: { profileOwner: 'user-123' },
        });
    });
});

describe('delete_profile_cascade_fn response', () => {
    it('aborts the pipeline when the handler returns a structured error', () => {
        const ctx = {
            stash: {},
            result: { __isError: true, errorCode: 'FORBIDDEN', message: 'not the profile owner' },
            error: null,
        };

        assert.throws(
            () => response(ctx),
            (err) => {
                assert.strictEqual(err.message, 'FORBIDDEN: not the profile owner');
                assert.deepStrictEqual(err.errorInfo, { errorCode: 'FORBIDDEN' });
                return true;
            }
        );
    });

    it('returns the handler result on success', () => {
        const ctx = {
            stash: {},
            result: { deletedCampaigns: 3, deletedOrders: 12 },
            error: null,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { deletedCampaigns: 3, deletedOrders: 12 });
    });
});
