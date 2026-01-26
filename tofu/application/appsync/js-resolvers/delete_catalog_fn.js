import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const catalogId = ctx.args.catalogId;
    // Normalize catalogId to ensure CATALOG# prefix
    const dbCatalogId = catalogId && catalogId.startsWith('CATALOG#') ? catalogId : `CATALOG#${catalogId}`;
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
