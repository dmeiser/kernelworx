import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: ctx.args.input.catalogId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Catalog not found', 'NOT_FOUND');
    }

    // INTERNAL: catalog existence lookup for the createSharedCampaign pipeline —
    // this is not the getCatalog query resolver, and the catalog is never
    // returned to the caller (the pipeline responds with the shared campaign).
    // Read authorization for the getCatalog query is enforced in
    // tofu/application/appsync/mapping-templates/get_catalog_response.vtl.
    // WRITE ACCESS: Only owner can update/delete (checked in update/delete resolvers).
    const catalog = ctx.result;
    if (catalog.isDeleted === true) {
        util.error('Catalog has been deleted', 'NOT_FOUND');
    }

    // #706: enforce the same visibility rule as getCatalog (#509) — a catalog
    // may only be referenced by createSharedCampaign when it is public,
    // admin-managed, or owned by the caller. Without this check any
    // authenticated user could attach another user's private catalog to a
    // shared campaign and read its products via the SharedCampaign.catalog
    // field resolver (IDOR) or block the owner from deleting it (DoS).
    const callerAccountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    if (!(catalog.isPublic === true || catalog.catalogType === 'ADMIN_MANAGED' || catalog.ownerAccountId === callerAccountId)) {
        util.error('Catalog not found', 'NOT_FOUND');
    }

    ctx.stash.catalog = catalog;
    return catalog;
}
