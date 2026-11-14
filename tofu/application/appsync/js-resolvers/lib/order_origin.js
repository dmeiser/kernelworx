// Order origin capture (§1.4.3, API-FIX-05; data model §5.6; API contract §10).
//
// A Scout Campaign row carries `unitId`/`unitCampaignId` as its *latest* joined
// scope, and removal deliberately retains that pair so joined history survives.
// Reading it back at sale time therefore answers a different question than the
// Order is asking: after a Scout leaves Unit A and joins Unit B, the campaign row
// says B, and every Order that asks the campaign where it was sold moves old
// demand -- and unfulfilled public Orders -- into Unit B's Council numbers.
//
// The membership guard (data model §5.6: `SCOUT_CAMPAIGN#<campaignId>` /
// `MEMBERSHIP_GUARD`) is the only current answer to "which Unit Campaign is this
// campaign joined to right now": `activeUnitCampaignId` is written only while a
// join is live, and removal clears it. So the origin is read from the guard, which
// is a strongly consistent Get on the unit_campaigns table, and the Unit itself
// comes from that Unit Campaign's own metadata row -- never from the campaign's
// retained link, and never from the campaignId-index projection, which is
// eventually consistent on top of a field that is already retroactive.
//
// An independent campaign records both fields as null, which makes "independent"
// a recorded fact rather than an absence that later acquires a meaning.

// The Unit Campaign this campaign is joined to *now*, or null when it is joined to
// none. Plain String() rather than a template literal: esbuild inlines this module
// into resolvers Terraform loads with templatefile(), and a dollar-brace sequence
// there is parsed as a Terraform expression and fails every plan (#570).
export function currentUnitCampaignId(guard) {
    if (!guard || guard.activeUnitCampaignId == null) {
        return null;
    }
    return String(guard.activeUnitCampaignId);
}

// The joined scope to stamp on an Order. `guard` is the strongly read membership
// guard; `unitCampaign` is the metadata row of the Unit Campaign the guard points
// at (absent when there is no current join, or when that row is gone).
export function orderOrigin(guard, unitCampaign) {
    const unitCampaignId = currentUnitCampaignId(guard);
    const unitId = unitCampaign && unitCampaign.unitId != null ? String(unitCampaign.unitId) : null;
    return { unitId: unitId, unitCampaignId: unitCampaignId };
}
