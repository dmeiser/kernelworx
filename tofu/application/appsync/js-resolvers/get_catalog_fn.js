import { util } from '@aws-appsync/utils';

/**
 * Retrieves a catalog by catalogId.
 *
 * This function performs an unconstrained GetItem. Access rules
 * (public/private visibility, soft-delete, ownership) are enforced
 * by the getCatalog response template and the Campaign.catalog /
 * SharedCampaign.catalog field response templates.
 */
export function request(ctx) {
    const rawCatalogId = ctx.stash.catalogId;
    if (!rawCatalogId) {
        util.error('Catalog ID not found in stash', 'BadRequest');
    }
    // Normalize to DB format: ensure it starts with CATALOG#
    const catalogId = (typeof rawCatalogId === 'string' && rawCatalogId.startsWith('CATALOG#')) ? rawCatalogId : 'CATALOG#' + rawCatalogId;
    // Save normalized id back to stash so downstream functions see the DB key
    ctx.stash.catalogId = catalogId;
    // Direct GetItem on catalogs table
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ catalogId: catalogId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Catalog not found for id: ' + ctx.stash.catalogId, 'NotFound');
    }

    // Store catalog in stash for CreateOrderFn.
    // Access rules are enforced by the getCatalog / Campaign.catalog /
    // SharedCampaign.catalog response templates that consume this result.
    ctx.stash.catalog = ctx.result;
    
    return ctx.result;
}
