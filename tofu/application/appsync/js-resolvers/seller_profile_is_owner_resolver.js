import { util } from '@aws-appsync/utils';
import { isProfileOwner } from './lib/owner_key.js';

export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Same predicate as seller_profile_permissions_resolver.js - see
    // lib/owner_key.js. Handles both prefixed (ACCOUNT#xxx) and clean (xxx)
    // ownerAccountId.
    return isProfileOwner(ctx.identity.sub, ctx.source.ownerAccountId);
}
