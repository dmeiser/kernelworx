import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_preferences_for_update_fn.js';

describe('get_preferences_for_update_fn request', () => {
    it('builds a consistent GetItem on the caller account', () => {
        const ctx = { identity: { sub: 'user-uuid-1' } };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-uuid-1' });
    });

    it('does not double-prefix an already-prefixed sub', () => {
        const ctx = { identity: { sub: 'ACCOUNT#user-uuid-2' } };
        assert.deepStrictEqual(request(ctx).key, { accountId: 'ACCOUNT#user-uuid-2' });
    });
});

describe('get_preferences_for_update_fn response', () => {
    it('stashes the raw preferences snapshot when present', () => {
        const stash = {};
        const readPreferences = { showReadOnlyProfiles: true, paymentMethods: [{ name: 'Cash App' }] };
        const ctx = {
            result: { accountId: 'ACCOUNT#user-uuid-1', preferences: readPreferences },
            stash,
        };
        assert.deepStrictEqual(response(ctx), ctx.result);
        assert.strictEqual(stash.readPreferencesExisted, true);
        assert.strictEqual(stash.readPreferences, readPreferences);
    });

    it('marks the snapshot as absent when the account has no preferences', () => {
        const stash = {};
        const ctx = {
            result: { accountId: 'ACCOUNT#user-uuid-1' },
            stash,
        };
        assert.deepStrictEqual(response(ctx), ctx.result);
        assert.strictEqual(stash.readPreferencesExisted, false);
        assert.strictEqual(stash.readPreferences, undefined);
    });

    it('re-throws datastore errors unchanged', () => {
        const ctx = {
            error: { message: 'Provisioned throughput exceeded', type: 'DynamoDB:ProvisionedThroughputExceededException' },
            stash: {},
        };
        assert.throws(
            () => response(ctx),
            /DynamoDB:ProvisionedThroughputExceededException: Provisioned throughput exceeded/
        );
    });
});
