import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const campaign = ctx.stash.campaign;
    
    // If campaign doesn't exist (lookup failed), skip the delete operation
    // This makes deleteCampaign idempotent - deleting a non-existent campaign returns true
    if (!campaign) {
        // Return a no-op - the response will return true anyway
        ctx.stash.skipDelete = true;
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', campaignId: 'NOOP' })
        };
    }
    
    // V2: Use composite key (profileId, campaignId) - campaignId is the SK
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ profileId: campaign.profileId, campaignId: campaign.campaignId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
