import { util, runtime } from '@aws-appsync/utils';

// Owner-only gate for both public-order settings pipelines (#679 settings
// slice, decision D8). It runs immediately after the two-phase write-access
// pair (verify_profile_write_access + verify_profile_write_access_step2) and
// refuses anyone who is not the profile owner: a WRITE-share collaborator, a
// READ-share collaborator, and a caller who cannot resolve the profile at all.
//
// The gate must emit FORBIDDEN itself. The pair's step-2 silent-deny branch
// (parentTypeName === 'Query' plus a GSI miss, verify_profile_write_access_fn.js)
// leaves a NULL stash rather than the write path's NOT_FOUND, so a stranger and
// a nonexistent profile reach here identically. Keeping one message for both is
// what stops the settings query from becoming a profile-existence oracle.
//
// Enabling publishes the profile's payment QR images to anonymous buyers and
// opens anonymous writes, and the acknowledgements are the owner's, so a
// collaborator must not be able to turn it on, read the share token, or rotate
// it. FORBIDDEN (not UNAUTHORIZED) is the code for a failed ownership check on
// an already-authenticated caller.
//
// No datastore call is made: the pair already decided ownership, so request()
// early-returns and the datasource call is skipped entirely.
export function request(ctx) {
    if (ctx.stash && ctx.stash.isOwner === true) {
        return runtime.earlyReturn({ authorized: true });
    }
    util.error('Only the profile owner can manage public order settings', 'FORBIDDEN');
    return runtime.earlyReturn({ authorized: false });
}

export function response(ctx) {
    // Unreachable in the AppSync runtime: request() either early-returns (the
    // runtime skips response()) or aborts the pipeline through util.error.
    // Present because the APPSYNC_JS resolver contract requires both handlers.
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.prev ? ctx.prev.result : { authorized: true };
}
