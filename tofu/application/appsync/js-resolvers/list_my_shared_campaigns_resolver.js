import { util } from '@aws-appsync/utils';
import { stripIdPrefix } from './lib/ids.js';

export function request(ctx) {
    const createdBy = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    return {
        operation: 'Query',
        index: 'GSI1',
        query: {
            expression: 'createdBy = :createdBy',
            expressionValues: util.dynamodb.toMapValues({ ':createdBy': createdBy })
        },
        scanIndexForward: false  // Most recent first
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Filter out inactive shared campaigns (for loop instead of filter())
    const items = ctx.result.items || [];
    const activeItems = [];
    for (const item of items) {
        // Set default value for null/undefined isActive
        if (item.isActive == null) {
            item.isActive = true;
        }
        
        if (item.isActive !== false) {
            // Normalize createdBy: strip ACCOUNT# prefix for GraphQL ID type
            if (item && item.createdBy) {
                item.createdBy = stripIdPrefix(item.createdBy, 'ACCOUNT#');
            }
            activeItems.push(item);
        }
    }
    return activeItems;
}
