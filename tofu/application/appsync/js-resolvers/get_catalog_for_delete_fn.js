import { util } from '@aws-appsync/utils';

/**
 * WRITE ACCESS: Only owner can delete catalog (or admin).
 * Verifies ownership before allowing deletion.
 */
export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    // Normalize catalogId for direct GetItem
    const dbCatalogId = catalogId && catalogId.startsWith('CATALOG#') ? catalogId : `CATALOG#${catalogId}`;
    // Store caller ID for authorization check
    ctx.stash.callerId = ctx.identity.sub;
    // Get catalog using catalogId as primary key
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
        catalogId: dbCatalogId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Catalog not found', 'NOT_FOUND');
    }
    
    const catalog = ctx.result;
    const callerId = ctx.stash.callerId;
    
    // Check admin status from JWT cognito:groups claim (source of truth)
    // Handle both array and string format for groups
    const groupsClaim = ctx.identity.claims['cognito:groups'];
    let groups = [];
    if (Array.isArray(groupsClaim)) {
        groups = groupsClaim;
    } else if (typeof groupsClaim === 'string') {
        groups = [groupsClaim];
    }
    // Check for 'admin' (lowercase) - standard Cognito group name
    const isAdmin = groups.includes('admin') || groups.includes('ADMIN');
    // MFA status from the JWT amr claim (source of truth), mirroring is_admin's
    // claims path. An admin may only use admin privileges after MFA (#336).
    const amrClaim = ctx.identity.claims['amr'];
    let amr = [];
    if (Array.isArray(amrClaim)) {
        amr = amrClaim;
    } else if (typeof amrClaim === 'string') {
        amr = [amrClaim];
    }
    const hasMfa = amr.includes('mfa');
    // ownerAccountId now has 'ACCOUNT#' prefix
    const isOwner = catalog.ownerAccountId === 'ACCOUNT#' + callerId;
    
    // Authorization logic:
    // - Owner can delete their own catalogs (no MFA needed)
    // - Admin can delete ANY catalog (both USER_CREATED and ADMIN_MANAGED),
    //   but only with MFA
    if (isOwner) {
        ctx.stash.authorized = true;
    } else if (isAdmin && hasMfa) {
        ctx.stash.authorized = true;
    } else if (isAdmin) {
        // Admin without MFA. Message must be exactly 'MFA required' (#336).
        util.error('MFA required', 'FORBIDDEN');
    } else {
        util.error('Not authorized to delete this catalog', 'FORBIDDEN');
    }
    
    ctx.stash.catalog = catalog;
    return catalog;
}
