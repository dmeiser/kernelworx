import { util } from '@aws-appsync/utils';
import { ownerGetItemRequest } from './lib/owner_key.js';

export function request(ctx) {
    // Read directly from the base table to avoid profileId-index GSI propagation races.
    return ownerGetItemRequest(ctx.identity.sub, ctx.args.input.profileId);
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // If the item exists under the caller's partition key, they are the owner.
    const profile = ctx.result;
    if (!profile) {
        util.error('Forbidden: Only profile owner can share profiles', 'FORBIDDEN');
    }
    ctx.stash.profile = profile;
    return profile;
}
