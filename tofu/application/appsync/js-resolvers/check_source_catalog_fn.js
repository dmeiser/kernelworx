/**
 * First step of the Campaign.catalog / SharedCampaign.catalog pipeline field
 * resolvers (see #332).
 *
 * List-query pipelines (listCampaignsByProfile, listMySharedCampaigns,
 * findSharedCampaigns) attach `catalog` to every campaign via a single
 * BatchGetItem. This function surfaces that pre-resolved value so the
 * follow-up GetItem function can skip its DynamoDB read. Singular queries
 * (getCampaign, getSharedCampaign, the campaign mutations, latestCampaign)
 * leave `catalog` off the source object; this function then returns
 * undefined and the GetItem step runs exactly as the old VTL field resolver
 * did.
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // NOTE: the AppSync JS runtime rejects the `in` operator at
    // CreateFunction ("The code contains one or more errors"); an undefined
    // check is equivalent here — the batch step only ever attaches `catalog`
    // as an object or null, never as an explicit undefined.
    if (ctx.source && ctx.source.catalog !== undefined) {
        return ctx.source.catalog;
    }
    return undefined;
}
