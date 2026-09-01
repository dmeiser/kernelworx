import { util } from '@aws-appsync/utils';

/**
 * Checks whether the catalog is referenced by any shared campaigns.
 *
 * Mirrors the CheckCatalogUsage constraint: a catalog that is still linked to
 * shared campaigns cannot be deleted, because the shared link would outlive the
 * catalog and could be used to create campaigns that are no longer tied to the
 * intended catalog.
 */
export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    // Normalize catalogId to ensure CATALOG# prefix
    const dbCatalogId = catalogId && catalogId.startsWith('CATALOG#') ? catalogId : `CATALOG#${catalogId}`;

    return {
        operation: 'Query',
        index: 'catalogId-index',
        query: {
            expression: 'catalogId = :catalogId',
            expressionValues: util.dynamodb.toMapValues({
                ':catalogId': dbCatalogId
            })
        },
        limit: 5  // Only need a few to confirm usage
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const sharedCampaigns = ctx.result.items || [];

    if (sharedCampaigns.length > 0) {
        const message = 'Cannot delete catalog: ' + sharedCampaigns.length + ' shared campaign(s) are referencing it. Please delete those shared campaigns first.';
        util.error(message, 'CatalogInUse');
    }

    return ctx.prev.result;  // Pass through catalog from previous step
}
