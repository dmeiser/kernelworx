/**
 * SellerProfile.latestCampaign / SharedProfile.latestCampaign field resolver.
 *
 * Two read paths (#331):
 *
 * 1. Denormalized fast path — the profile item carries latestCampaignId
 *    (stamped by the createCampaign/updateCampaign/deleteCampaign pipelines).
 *    A single GetItem fetches the campaign. A pointer that is dangling
 *    (campaign deleted) or stale-inactive resolves to null; the write-path
 *    maintenance in the campaign pipelines keeps the pointer canonical, so
 *    this is only reachable in a concurrent-mutation race window.
 *
 * 2. Unmigrated fallback — profiles without latestCampaignId (existing rows
 *    predating the denormalization, until their next campaign mutation) run
 *    the original per-item Query against the profileId-createdAt-index with
 *    the same active-only filter, so behavior never regresses for them.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profileId = ctx.source.profileId;
    // Add PROFILE# prefix for DynamoDB if not present
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;

    const latestCampaignId = ctx.source.latestCampaignId;
    if (latestCampaignId) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({
                profileId: dbProfileId,
                campaignId: latestCampaignId,
            }),
        };
    }

    return {
        operation: 'Query',
        index: 'profileId-createdAt-index',  // Use GSI sorted by createdAt
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        },
        filter: {
            expression: 'isActive = :isActive OR attribute_not_exists(isActive)',
            expressionValues: util.dynamodb.toMapValues({ ':isActive': true })
        },
        scanIndexForward: false  // Descending order (newest first)
        // Note: No limit here because DynamoDB applies limit BEFORE filter
        // We filter in the response function instead
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    if (ctx.source.latestCampaignId) {
        // Denormalized GetItem path.
        const campaign = ctx.result;
        if (!campaign || campaign.isActive === false) {
            // Dangling pointer (campaign deleted) or stale-inactive: the
            // campaign pipelines maintain latestCampaignId, so this is only
            // a concurrent-mutation race; canonical result is "no latest".
            return null;
        }
        if (campaign.isActive == null) {
            campaign.isActive = true;
        }
        return campaign;
    }

    const items = ctx.result.items || [];
    if (items.length === 0) {
        return null;  // No active campaigns for this profile
    }

    // GSI sorts by createdAt descending, filter reduces to active campaigns
    // With limit: 1, we get exactly the most recent active campaign
    const campaign = items[0];

    // Set default value for null/undefined isActive (backward compatibility)
    if (campaign.isActive == null) {
        campaign.isActive = true;
    }

    return campaign;
}
