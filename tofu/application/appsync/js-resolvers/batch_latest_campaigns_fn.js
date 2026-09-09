/**
 * Batch-fetch the denormalized latest campaigns for a page of profiles in a
 * single BatchGetItem call (replaces the per-profile DynamoDB Query field
 * resolver for migrated rows; see #331).
 *
 * Runs as the last step of the listMyProfiles pipeline, after
 * list_my_profiles_fn. The previous result is the SellerProfileConnection
 * shape: { profiles: [...], nextToken }.
 *
 * Profiles that carry a latestCampaignId denormalized field (set on campaign
 * create/update/delete) get latestCampaign attached from the batch result.
 * Profiles WITHOUT latestCampaignId (unmigrated rows) are left untouched so
 * the SellerProfile.latestCampaign field resolver still runs its per-item
 * fallback Query — behavior never regresses for unmigrated rows.
 *
 * Fetched campaigns that are inactive or missing from the batch result are
 * also left unannotated: the field resolver re-reads by id and applies the
 * same active check, so a stale pointer degrades to the field-resolver path
 * instead of returning wrong data.
 */
// WARNING: this file is loaded via Terraform templatefile() (see
// modules/appsync/functions_profiles.tf), so every `${...}` below is
// Terraform-interpolated, not a JS template literal. `${campaigns_table_name}`
// is the only intended placeholder; do NOT add other `${...}` sequences here.
import { util, runtime } from '@aws-appsync/utils';

const tableName = '${campaigns_table_name}';

function normalizeProfileId(profileId) {
    return (typeof profileId === 'string' && profileId.startsWith('PROFILE#'))
        ? profileId
        : 'PROFILE#' + profileId;
}

export function request(ctx) {
    const connection = ctx.prev.result || { profiles: [] };
    const profiles = connection.profiles || [];

    const keys = [];
    for (const profile of profiles) {
        if (profile && profile.latestCampaignId) {
            keys.push(util.dynamodb.toMapValues({
                profileId: normalizeProfileId(profile.profileId),
                campaignId: profile.latestCampaignId,
            }));
        }
    }

    // Skip the BatchGetItem and pass the connection through unchanged when
    // no profile carries the denormalized field, or when the page yields too
    // many keys for a single BatchGetItem (100-key cap; an AppSync function
    // can issue only one call). Oversized pages fall back to the per-item
    // field resolver for every profile instead of failing the whole query.
    if (keys.length === 0 || keys.length > 100) {
        return runtime.earlyReturn(connection);
    }

    return {
        operation: 'BatchGetItem',
        tables: {
            [tableName]: {
                keys: keys,
            },
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const connection = ctx.prev.result || { profiles: [] };
    const profiles = connection.profiles || [];

    const tableData = (ctx.result && ctx.result.data && ctx.result.data[tableName]) || [];
    const campaignsById = {};
    for (const campaign of tableData) {
        // Only ACTIVE campaigns may satisfy latestCampaign (canonical
        // semantics of the old per-item Query). An inactive hit means the
        // pointer is stale; leave the profile unannotated so the field
        // resolver re-checks by id.
        if (campaign && campaign.campaignId && campaign.isActive !== false) {
            if (campaign.isActive == null) {
                campaign.isActive = true;
            }
            campaignsById[campaign.campaignId] = campaign;
        }
    }

    return {
        ...connection,
        profiles: profiles.map(profile => {
            if (!profile || !profile.latestCampaignId) {
                return profile;
            }
            const campaign = campaignsById[profile.latestCampaignId];
            if (!campaign) {
                // Missing or inactive: leave for the field resolver fallback.
                return profile;
            }
            return { ...profile, latestCampaign: campaign };
        }),
    };
}
