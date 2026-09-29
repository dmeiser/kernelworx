import { describe, it } from 'node:test';
import assert from 'node:assert';
import { expectedOwnerKey, ownerGetItemRequest } from './owner_key.js';
import { request as inviteRequest } from '../verify_profile_owner_for_invite_fn.js';
import { request as revokeRequest } from '../verify_profile_owner_for_revoke_fn.js';
import { request as shareRequest } from '../verify_profile_owner_for_share_fn.js';

describe('expectedOwnerKey', () => {
    it('prepends ACCOUNT# when prefix is missing', () => {
        assert.strictEqual(expectedOwnerKey('user-123'), 'ACCOUNT#user-123');
    });

    it('preserves ACCOUNT# when already present', () => {
        assert.strictEqual(expectedOwnerKey('ACCOUNT#user-123'), 'ACCOUNT#user-123');
    });

    it('returns null for falsy or non-string values', () => {
        assert.strictEqual(expectedOwnerKey(null), null);
        assert.strictEqual(expectedOwnerKey(''), null);
        assert.strictEqual(expectedOwnerKey(undefined), null);
        assert.strictEqual(expectedOwnerKey(123), null);
    });
});

describe('ownerGetItemRequest', () => {
    it('constructs strongly consistent GetItem with normalized keys', () => {
        const req = ownerGetItemRequest('user-123', 'prof-456');
        assert.strictEqual(req.operation, 'GetItem');
        assert.strictEqual(req.consistentRead, true);
        assert.deepStrictEqual(req.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
    });

    it('preserves already-prefixed sub and profileId', () => {
        const req = ownerGetItemRequest('ACCOUNT#user-123', 'PROFILE#prof-456');
        assert.strictEqual(req.operation, 'GetItem');
        assert.strictEqual(req.consistentRead, true);
        assert.deepStrictEqual(req.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
    });
});

describe('owner verifiers consistency across implementations', () => {
    const testCases = [
        { sub: 'user-123', profileId: 'prof-456' },
        { sub: 'ACCOUNT#user-123', profileId: 'prof-456' },
        { sub: 'user-123', profileId: 'PROFILE#prof-456' },
        { sub: 'ACCOUNT#user-123', profileId: 'PROFILE#prof-456' }
    ];

    for (const tc of testCases) {
        it(`produces identical GetItem request for sub=${tc.sub}, profileId=${tc.profileId}`, () => {
            const ctx = {
                identity: { sub: tc.sub },
                args: { input: { profileId: tc.profileId } }
            };
            const expected = ownerGetItemRequest(tc.sub, tc.profileId);
            const inviteResult = inviteRequest(ctx);
            const revokeResult = revokeRequest(ctx);
            const shareResult = shareRequest(ctx);

            assert.deepStrictEqual(inviteResult, expected);
            assert.deepStrictEqual(revokeResult, expected);
            assert.deepStrictEqual(shareResult, expected);
        });
    }
});
