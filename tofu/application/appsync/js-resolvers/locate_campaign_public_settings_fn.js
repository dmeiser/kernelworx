import { util } from '@aws-appsync/utils';
import { requestCampaignId } from './lib/public_settings.js';

// Locator step, first in both campaign-level public-order settings pipelines
// (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1). The settings are keyed by campaign, but
// the Campaigns base table is keyed {profileId, campaignId}, so a campaignId
// alone cannot address the row: this step reads the campaignId-index GSI purely
// to learn the partition key.
//
// The GSI row is a LOCATOR and nothing else. Ownership is decided downstream by
// the two-phase write-access pair's strongly consistent base-table read of the
// Profiles item under the caller's own account (#438), and the settings
// themselves are re-read consistently by the next CampaignsDS step, because a
// GSI projection can lag a write the owner just made. Handing the located item
// to the pair through ctx.stash.campaign is what lets the pair resolve the
// profileId without the client ever naming a profile.
//
// A campaignId that resolves to no row is NOT_FOUND. Campaign existence is
// already observable to any authenticated caller through getCampaign (which
// answers null), so this is not a new oracle; a campaign that exists but belongs
// to another account reaches the owner gate and answers FORBIDDEN.
export function request(ctx) {
    const campaignId = requestCampaignId(ctx);
    if (!campaignId) {
        util.error('campaignId is required', 'INVALID_INPUT');
        return;
    }

    return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return;
    }

    const items = ctx.result && ctx.result.items ? ctx.result.items : [];
    if (items.length === 0) {
        util.error('Campaign not found', 'NOT_FOUND');
        return;
    }

    const campaign = items[0];
    if (!campaign.profileId) {
        // A GSI projection without the base-table partition key cannot be
        // addressed consistently; treat it as not found rather than guessing.
        util.error('Campaign not found', 'NOT_FOUND');
        return;
    }

    // The write-access pair resolves the profileId from exactly this stash slot
    // (verify_profile_write_access_fn.js resolveDbProfileId).
    if (ctx.stash) {
        ctx.stash.campaign = campaign;
    }
    return campaign;
}
