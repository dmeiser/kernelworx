import { util } from '@aws-appsync/utils';
import { normalizeCatalogsIsPublic } from './lib/normalize_catalog.js';

export function request(ctx) {
    const ownerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    return {
        operation: 'Query',
        index: 'ownerAccountId-index',
        query: {
            expression: 'ownerAccountId = :ownerAccountId',
            expressionValues: util.dynamodb.toMapValues({ ':ownerAccountId': ownerAccountId })
        },
        filter: {
            expression: 'attribute_not_exists(isDeleted) OR isDeleted = :false',
            expressionValues: util.dynamodb.toMapValues({ ':false': false })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return normalizeCatalogsIsPublic(ctx.result.items || []);
}
