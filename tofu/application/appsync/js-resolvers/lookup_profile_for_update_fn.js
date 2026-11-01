import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    // Owned by lib/ids.js, same as verify_profile_write_access_fn.js, so both
    // write-permission checks resolve a clean, unprefixed id to the same
    // PROFILE# DB form; a re-inlined ternary here is caught by
    // tests/unit/check_id_prefix_normalization.test.ts.
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');
    // Idempotent: a sub that already carries ACCOUNT# is left alone.
    const expectedOwner = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            ownerAccountId: expectedOwner,
            profileId: dbProfileId
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const profile = ctx.result;
    if (!profile) {
        util.error('Profile not found or access denied', 'FORBIDDEN');
    }
    ctx.stash.profile = profile;
    return profile;
}

