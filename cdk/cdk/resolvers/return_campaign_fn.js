import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // No-op request (using None data source)
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If campaign not found, return null
    if (ctx.stash.campaignNotFound) {
        return null;
    }
    
    // If not authorized, return null (query permissions model - don't error)
    if (!ctx.stash.authorized) {
        return null;
    }
    
    // Authorized - return the campaign with field mapping
    const campaign = ctx.stash.campaign;
    // Map DynamoDB field campaignId to GraphQL field campaignId
    campaign.campaignId = campaign.campaignId;
    return campaign;
}
