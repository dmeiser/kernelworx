/**
 * Shared spec for the verify_profile_owner_for_* resolver family.
 *
 * The three resolvers implement one behavior: read the profile from the base
 * table under the caller's own partition key, so an item found there proves
 * ownership, and refuse everything else. Since #534 the shared key
 * construction lives in lib/owner_key.js (ownerGetItemRequest), so the three
 * files differ only in their FORBIDDEN message; every behavioral expectation
 * is asserted once, here, for all families.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert';

import { request as shareRequest, response as shareResponse } from '../verify_profile_owner_for_share_fn.js';
import { request as inviteRequest, response as inviteResponse } from '../verify_profile_owner_for_invite_fn.js';
import { request as revokeRequest, response as revokeResponse } from '../verify_profile_owner_for_revoke_fn.js';

export const PROFILE_OWNER_FAMILIES = {
    share: {
        resolver: 'verify_profile_owner_for_share_fn',
        request: shareRequest,
        response: shareResponse,
        forbiddenMessage: 'Forbidden: Only profile owner can share profiles',
    },
    invite: {
        resolver: 'verify_profile_owner_for_invite_fn',
        request: inviteRequest,
        response: inviteResponse,
        forbiddenMessage: 'Forbidden: Only profile owner can create invites',
    },
    revoke: {
        resolver: 'verify_profile_owner_for_revoke_fn',
        request: revokeRequest,
        response: revokeResponse,
        forbiddenMessage: 'Forbidden: Only profile owner can revoke shares',
    },
};

/**
 * Runs the family contract against one registered family. Every family member
 * gets the same assertions, so a change to the shared behavior is made once.
 */
export function describeVerifyProfileOwnerFamily(familyKey) {
    const family = PROFILE_OWNER_FAMILIES[familyKey];

    if (!family) {
        throw new Error(`Unknown verify_profile_owner family: ${familyKey}`);
    }

    describe(`${family.resolver} request`, () => {
        it('builds a strongly consistent owner-keyed GetItem with normalized ids', () => {
            const result = family.request({
                identity: { sub: 'user-123' },
                args: { input: { profileId: 'prof-456' } },
                stash: {},
            });

            assert.strictEqual(result.operation, 'GetItem');
            assert.deepStrictEqual(result.key, {
                ownerAccountId: 'ACCOUNT#user-123',
                profileId: 'PROFILE#prof-456',
            });
            assert.strictEqual(result.consistentRead, true);
        });

        it('does not re-prefix an already-normalized profileId', () => {
            const result = family.request({
                identity: { sub: 'user-123' },
                args: { input: { profileId: 'PROFILE#prof-456' } },
                stash: {},
            });

            assert.strictEqual(result.operation, 'GetItem');
            assert.deepStrictEqual(result.key, {
                ownerAccountId: 'ACCOUNT#user-123',
                profileId: 'PROFILE#prof-456',
            });
            assert.strictEqual(result.consistentRead, true);
        });

        it('leaves an already-prefixed caller sub alone (#534)', () => {
            const result = family.request({
                identity: { sub: 'ACCOUNT#user-123' },
                args: { input: { profileId: 'PROFILE#prof-456' } },
                stash: {},
            });

            assert.deepStrictEqual(result.key, {
                ownerAccountId: 'ACCOUNT#user-123',
                profileId: 'PROFILE#prof-456',
            });
        });
    });

    describe(`${family.resolver} response`, () => {
        it('stashes and returns the profile when the caller owns it', () => {
            const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#user-123', name: 'Test' };
            const ctx = { stash: {}, result: profile };

            const result = family.response(ctx);

            assert.deepStrictEqual(result, profile);
            assert.deepStrictEqual(ctx.stash.profile, profile);
        });

        it('throws FORBIDDEN with this family message when the caller does not own the profile', () => {
            assert.throws(
                () => family.response({ stash: {}, result: null }),
                (error) => error.message === `FORBIDDEN: ${family.forbiddenMessage}`
            );
        });

        it('rethrows a DynamoDB error untouched', () => {
            assert.throws(
                () => family.response({ stash: {}, error: { message: 'DynamoDB error', type: 'DynamoDBException' } }),
                /DynamoDBException: DynamoDB error/
            );
        });
    });
}
