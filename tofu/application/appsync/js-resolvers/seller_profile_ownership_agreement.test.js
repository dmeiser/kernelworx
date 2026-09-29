import { describe, it } from 'node:test';
import assert from 'node:assert';

// seller_profile_is_owner_resolver.js and seller_profile_permissions_resolver.js
// are the two field resolvers on SellerProfile that answer "is the caller the
// owner?" from the same (ctx.identity.sub, ctx.source.ownerAccountId) pair.
// Written as two inline comparisons they drift: a prefixed sub made one say
// "owner" and the other "not owner". These tests drive both real resolvers.
import { response as isOwnerResponse } from './seller_profile_is_owner_resolver.js';
import { request as permissionsRequest, response as permissionsResponse } from './seller_profile_permissions_resolver.js';

const OWNERSHIP_CASES = [
    { name: 'a bare sub against a prefixed owner', sub: 'user-123', ownerAccountId: 'ACCOUNT#user-123', expectedOwner: true },
    { name: 'a bare sub against a bare owner', sub: 'user-123', ownerAccountId: 'user-123', expectedOwner: true },
    { name: 'an already-prefixed sub against a prefixed owner', sub: 'ACCOUNT#user-123', ownerAccountId: 'ACCOUNT#user-123', expectedOwner: true },
    // The drift: the old inline comparison answered false here while its
    // sibling, using normalizeId, answered true.
    { name: 'an already-prefixed sub against a bare owner', sub: 'ACCOUNT#user-123', ownerAccountId: 'user-123', expectedOwner: true },
    { name: 'a different caller', sub: 'user-999', ownerAccountId: 'ACCOUNT#user-123', expectedOwner: false }
];

describe('SellerProfile ownership agreement', () => {
    for (const { name, sub, ownerAccountId, expectedOwner } of OWNERSHIP_CASES) {
        it(`is_owner and permissions agree that the caller ${expectedOwner ? 'is' : 'is not'} owner: ${name}`, () => {
            const source = { ownerAccountId, profileId: 'PROFILE#prof-1' };

            const isOwner = isOwnerResponse({ identity: { sub }, source });

            const permsCtx = { identity: { sub }, source, stash: {} };
            permissionsRequest(permsCtx);
            permsCtx.result = null;
            const permissions = permissionsResponse(permsCtx);

            // permissions returns ['READ','WRITE'] for an owner, null otherwise.
            assert.strictEqual(isOwner, expectedOwner);
            if (expectedOwner) {
                assert.deepStrictEqual(permissions, ['READ', 'WRITE']);
            } else {
                assert.strictEqual(permissions, null);
            }
            // The two must never disagree, whatever the input form.
            assert.strictEqual(isOwner, permsCtx.stash.isOwner === true);
        });
    }

    it('denies ownership rather than granting it when the caller is missing', () => {
        const source = { ownerAccountId: null, profileId: 'PROFILE#prof-1' };

        const isOwner = isOwnerResponse({ identity: {}, source });

        const permsCtx = { identity: {}, source, stash: {} };
        permissionsRequest(permsCtx);
        permsCtx.result = null;
        const permissions = permissionsResponse(permsCtx);

        assert.strictEqual(isOwner, false);
        assert.strictEqual(permissions, null);
    });
});
