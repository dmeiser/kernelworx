import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const createdBy = ctx.identity.sub;
    return {
        operation: 'Query',
        index: 'GSI1',
        query: {
            expression: 'createdBy = :createdBy',
            expressionValues: util.dynamodb.toMapValues({ ':createdBy': createdBy })
        },
        select: 'COUNT'
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const count = ctx.result.scannedCount || 0;
    // Rate limit: 50 shared campaigns per user
    if (count >= 50) {
        util.error('Rate limit exceeded: Maximum 50 campaign shared campaigns per user', 'RateLimitExceeded');
    }
    ctx.stash.sharedCampaignCount = count;
    return count;
}
