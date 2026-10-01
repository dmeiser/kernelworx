// Contract for the shared owner-verification key construction (#534).
// The three verify_profile_owner_for_* resolvers all route through
// ownerGetItemRequest; this pins the behavior the family spec asserts per
// family, directly against the helper.
import { describe, it } from 'node:test';
import assert from 'node:assert';

import { expectedOwnerKey, ownerGetItemRequest } from './owner_key.js';

describe('expectedOwnerKey', () => {
    it('prefixes a bare caller sub', () => {
        assert.strictEqual(expectedOwnerKey('user-123'), 'ACCOUNT#user-123');
    });

    it('leaves an already-prefixed sub alone', () => {
        assert.strictEqual(expectedOwnerKey('ACCOUNT#user-123'), 'ACCOUNT#user-123');
    });
});

describe('ownerGetItemRequest', () => {
    it('builds a strongly consistent base-table GetItem keyed by owner and profile', () => {
        const result = ownerGetItemRequest('user-123', 'prof-456');
        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456',
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('does not re-prefix already-normalized ids', () => {
        const result = ownerGetItemRequest('ACCOUNT#user-123', 'PROFILE#prof-456');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456',
        });
    });
});
