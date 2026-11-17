import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import { parseFulfillmentMode, MODE_CONSUME_SCOUT_CUSTODY } from './lib/custody_sale.js';

// §2.4.2 authorizes a door-to-door custody sale two ways: the Profile Owner/WRITE path
// this function enforces for every order write, OR an admin of the Unit whose Scout the
// sale consumes. A Unit Admin may hold no share on the Profile at all, so for that one
// request this step records its verdict on the stash instead of ending the pipeline:
// create_order_fn then decides "Profile WRITE or Unit Admin" and denies with the same
// FORBIDDEN if neither holds. Nothing else -- not a NONE-mode order, not a reservation,
// not a campaign write -- can reach the non-fatal branch, because it is keyed on the
// field AppSync names for this resolver AND on the sale mode.
function isCustodySaleCreateOrder(ctx) {
    return !!(ctx.info && ctx.info.fieldName === 'createOrder') &&
        parseFulfillmentMode(ctx.args && ctx.args.input) === MODE_CONSUME_SCOUT_CUSTODY;
}

export function request(ctx) {
    // If already authorized (owner or skipAuth), skip this check
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Non-owner: check for WRITE share
    // Extract profileId using same logic as VerifyProfileWriteAccessFn
    let profileId = null;
    
    if (ctx.args.input && ctx.args.input.profileId) {
        profileId = ctx.args.input.profileId;
    } else if (ctx.stash && ctx.stash.order) {
        // Orders have profileId attribute - use it directly (not PK which is the campaign key)
        profileId = ctx.stash.order.profileId;
    } else if (ctx.stash && ctx.stash.campaign && ctx.stash.campaign.profileId) {
        // Campaigns have profileId attribute - use it directly (not PK which is composite)
        profileId = ctx.stash.campaign.profileId;
    }
    
    if (!profileId) {
        util.error('Profile ID not found for share check', 'INVALID_INPUT');
    }
    
    // Normalize profileId to ensure PROFILE# prefix for share lookup
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');
    const targetAccountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');

    // Look up share in shares table: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
        profileId: dbProfileId, 
        targetAccountId: targetAccountId 
        }),
        consistentRead: true
    };
}

// The denial this step has always issued, or the posture it hands downstream when the
// request is the one request allowed to answer the question a second way.
function denyOrDefer(ctx, message) {
    if (isCustodySaleCreateOrder(ctx)) {
        ctx.stash.profileWriteAuthorized = false;
        return { authorized: false };
    }
    util.error(message, 'FORBIDDEN');
}

export function response(ctx) {
    // If already authorized, return success
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        ctx.stash.profileWriteAuthorized = true;
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - access denied
    if (!share || !share.profileId) {
        return denyOrDefer(ctx, 'Forbidden: Only profile owner or users with WRITE permission can perform this action (no share found)');
    }
    
    // Share exists but doesn't have permissions field - deny
    if (!share.permissions || !Array.isArray(share.permissions)) {
        return denyOrDefer(ctx, 'Forbidden: Share exists but permissions are invalid');
    }
    
    // Check if caller has WRITE permission via share
    if (share.permissions.includes('WRITE')) {
        const profile = ctx.stash.profile;
        const currentOwner = profile && profile.ownerAccountId;
        if (share.ownerAccountId && currentOwner && share.ownerAccountId !== currentOwner) {
            return denyOrDefer(ctx, 'Forbidden: Only profile owner or users with WRITE permission can perform this action (share is no longer valid)');
        }
        ctx.stash.share = share;
        ctx.stash.profileWriteAuthorized = true;
        return { authorized: true };
    }
    
    // Share exists but only has READ permission - access denied
    // Log share details server-side only; never serialize internal objects into client-facing errors
    console.error(
        'Share permission check failed (READ only): ' +
            JSON.stringify({ profileId: share.profileId, permissions: share.permissions })
    );
    return denyOrDefer(ctx, 'Forbidden: Only profile owner or users with WRITE permission can perform this action (share has READ only)');
}
