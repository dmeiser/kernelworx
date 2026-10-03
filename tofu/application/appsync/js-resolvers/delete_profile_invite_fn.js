import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import { ownerGetItemRequest } from './lib/owner_key.js';

export function request(ctx) {
    // The owner-keyed strongly consistent GetItem has one owner (#438): the
    // same helper the three verify_profile_owner_for_* resolvers use. This was
    // the last inline copy of that key shape. The stash keeps the plain
    // normalized id (the helper's key is already DynamoDB-mapped), built
    // through the same ids.js owner so the two cannot drift.
    ctx.stash.profileId = normalizeIdOrPrefix(ctx.args.profileId, 'PROFILE#');
    return ownerGetItemRequest(ctx.identity.sub, ctx.args.profileId);
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result;
    if (!profile) {
        util.error('Forbidden: Only profile owner can delete invites', 'FORBIDDEN');
    }
    ctx.stash.inviteCode = ctx.args.inviteCode;
    ctx.stash.authorized = true;
    return true;
}
