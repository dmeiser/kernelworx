// Order origin capture (§1.4.3, API-FIX-05; API contract §10 extensions).
//
// A Scout Campaign carries `unitId`/`unitCampaignId` as its *latest* joined
// scope, and removal deliberately retains that pair so joined history survives
// (data model §5.6). That makes the link useless as a retroactive answer: if an
// Order asked the Campaign where the sale happened, joining a different Unit
// Campaign would silently move old demand — and unfulfilled public Orders — into
// the wrong Unit's Council numbers.
//
// So the joined scope is copied onto the Order row at creation and never derived
// again. An independent campaign records both as null, which is what makes
// "independent" a recorded fact rather than an absence that later acquires a
// meaning.

export function orderOrigin(campaign) {
    // Plain String() rather than a template literal: esbuild inlines this module
    // into a resolver that Terraform loads with templatefile(), and a dollar-brace
    // sequence there is parsed as a Terraform expression and fails every plan (#570).
    const unitId = campaign && campaign.unitId != null ? String(campaign.unitId) : null;
    const unitCampaignId = campaign && campaign.unitCampaignId != null ? String(campaign.unitCampaignId) : null;
    return { unitId: unitId, unitCampaignId: unitCampaignId };
}
