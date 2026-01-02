import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const campaignId = ctx.args.campaignId;
    // Query campaignId-index GSI to find the campaign (V2: PK=profileId, SK=campaignId)
    return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
        },
        consistentRead: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // For delete, if campaign not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (!ctx.result.items || ctx.result.items.length === 0) {
        ctx.stash.campaign = null;
        return null;
    }
    
    // Note: Authorization is simplified - relies on Cognito authentication
    // Full share-based authorization would require additional pipeline functions
    ctx.stash.campaign = ctx.result.items[0];
    return ctx.result.items[0];
}
