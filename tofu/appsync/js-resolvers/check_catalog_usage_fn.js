import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    // Normalize catalogId to ensure CATALOG# prefix
    const dbCatalogId = catalogId && catalogId.startsWith('CATALOG#') ? catalogId : `CATALOG#${catalogId}`;
    // Use GSI query instead of Scan for efficiency and consistency
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
    
    const campaigns = ctx.result.items || [];
    
    if (campaigns.length > 0) {
        // Catalog is in use - return error
        const message = 'Cannot delete catalog: ' + campaigns.length + ' campaign(s) are using it. Please update or delete those campaigns first.';
        util.error(message, 'CatalogInUse');
    }
    
    return ctx.prev.result;  // Pass through catalog from previous step
}
