import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    const dbCatalogId = normalizeIdOrPrefix(catalogId, 'CATALOG#');
    // Soft delete: mark isDeleted = true, keep record in table for orphan detection
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({
            catalogId: dbCatalogId
        }),
        update: {
            expression: 'SET isDeleted = :true',
            expressionValues: util.dynamodb.toMapValues({
                ':true': true
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
