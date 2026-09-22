import { util } from '@aws-appsync/utils';
import { normalizeCatalogsIsPublic } from './lib/normalize_catalog.js';

export function request(ctx) {
    // Query for public catalogs, then filter for ADMIN_MANAGED only
    return {
        operation: 'Query',
        index: 'isPublic-createdAt-index',
        query: {
            expression: 'isPublicStr = :isPublicStr',
            expressionValues: util.dynamodb.toMapValues({ ':isPublicStr': 'true' })
        },
        filter: {
            expression: '(attribute_not_exists(isDeleted) OR isDeleted = :false) AND catalogType = :adminManaged',
            expressionValues: util.dynamodb.toMapValues({ 
                ':false': false,
                ':adminManaged': 'ADMIN_MANAGED'
            })
        },
        scanIndexForward: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return normalizeCatalogsIsPublic(ctx.result.items || []);
}
