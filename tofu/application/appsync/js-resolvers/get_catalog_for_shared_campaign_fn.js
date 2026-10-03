import { util } from '@aws-appsync/utils';

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

    ctx.stash.catalog = catalog;
    return catalog;
}
