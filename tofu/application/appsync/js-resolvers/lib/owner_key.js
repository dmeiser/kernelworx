import { util } from '@aws-appsync/utils';
import { normalizeId } from './ids.js';

export function expectedOwnerKey(sub) {
    return normalizeId(sub, 'ACCOUNT#');
}

// The ownership comparison for a SellerProfile. Both field resolvers on the
// type - seller_profile_is_owner_resolver.js and
// seller_profile_permissions_resolver.js - read the same
// (ctx.identity.sub, ctx.source.ownerAccountId) pair, so the predicate lives
// here once: written twice, they drift, and a resolver that says "owner" while
// its sibling says "not owner" is exactly the shape that rots.
export function isProfileOwner(callerAccountId, ownerAccountId) {
    const normalizedCaller = expectedOwnerKey(callerAccountId);
    const normalizedOwner = normalizeId(ownerAccountId, 'ACCOUNT#');
    return normalizedCaller !== null && normalizedCaller === normalizedOwner;
}

// Owner-verification read for the #438 write-authz invariant: ownership is
// decided ONLY by a strongly consistent base-table GetItem keyed
// {ownerAccountId: <caller>, profileId} — never by the profileId-index GSI,
// which can keep projecting the previous owner right after a transfer.
export function ownerGetItemRequest(sub, profileId) {
    const expectedOwner = expectedOwnerKey(sub);
    const dbProfileId = normalizeId(profileId, 'PROFILE#');
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            ownerAccountId: expectedOwner,
            profileId: dbProfileId
        }),
        consistentRead: true
    };
}
