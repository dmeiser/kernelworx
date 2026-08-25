import { util } from '@aws-appsync/utils';

function buildUnitCampaignKey(unitType, unitNumber, city, state, campaignName, campaignYear) {
    return [unitType, unitNumber, city, state, campaignName, campaignYear].join('#');
}

function normalizeCatalogId(catalogId) {
    if (catalogId === null || catalogId === undefined) {
        return null;
    }
    return (typeof catalogId === 'string' && catalogId.startsWith('CATALOG#'))
        ? catalogId
        : 'CATALOG#' + catalogId;
}

export function request(ctx) {
    const campaign = ctx.stash.campaign;
    const input = ctx.args.input || ctx.args;

    // Build update expression dynamically
    const updates = [];
    const exprValues = {};
    const exprNames = {};

    if (input.campaignName !== undefined) {
        updates.push('campaignName = :campaignName');
        exprValues[':campaignName'] = input.campaignName;
    }
    if (input.startDate !== undefined) {
        updates.push('startDate = :startDate');
        exprValues[':startDate'] = input.startDate;
    }
    if (input.endDate !== undefined) {
        updates.push('endDate = :endDate');
        exprValues[':endDate'] = input.endDate;
    }
    if (input.catalogId !== undefined) {
        updates.push('catalogId = :catalogId');
        // Normalize catalogId to DB format (CATALOG#...)
        exprValues[':catalogId'] = normalizeCatalogId(input.catalogId);
    }
    if (input.isActive !== undefined) {
        updates.push('isActive = :isActive');
        exprValues[':isActive'] = input.isActive;
    }

    // Recompute unitCampaignKey whenever any of its components change so unit
    // reports/catalogs stay consistent. The key is derived from
    // unitType#unitNumber#city#state#campaignName#campaignYear. Issue #104
    // exposes additional editable fields; future schema changes must extend
    // this guard so the GSI key is never stale. We only emit the SET clause
    // when the campaign already has the unit fields (otherwise the original
    // code did not set a key either).
    const hasUnitContext = campaign.unitType !== undefined && campaign.unitNumber !== undefined;
    const componentChanged =
        input.campaignName !== undefined ||
        input.unitType !== undefined ||
        input.unitNumber !== undefined ||
        input.city !== undefined ||
        input.state !== undefined ||
        input.campaignYear !== undefined;
    if (hasUnitContext && componentChanged) {
        const newKey = buildUnitCampaignKey(
            input.unitType !== undefined ? input.unitType : campaign.unitType,
            input.unitNumber !== undefined ? input.unitNumber : campaign.unitNumber,
            input.city !== undefined ? input.city : campaign.city || '',
            input.state !== undefined ? input.state : campaign.state || '',
            input.campaignName !== undefined ? input.campaignName : campaign.campaignName,
            input.campaignYear !== undefined ? input.campaignYear : campaign.campaignYear
        );
        updates.push('unitCampaignKey = :unitCampaignKey');
        exprValues[':unitCampaignKey'] = newKey;
    }

    // Always update updatedAt
    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();

    if (updates.length === 0) {
        return campaign; // No updates, return original
    }

    const updateExpression = 'SET ' + updates.join(', ');

    // V2: Use composite key (profileId, campaignId) - campaignId is the SK
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: campaign.profileId, campaignId: campaign.campaignId }),
        update: {
        expression: updateExpression,
        expressionNames: Object.keys(exprNames).length > 0 ? exprNames : undefined,
        expressionValues: util.dynamodb.toMapValues(exprValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const campaign = ctx.stash.campaign;
    const input = ctx.args.input || ctx.args;

    // Start with existing campaign data to preserve all fields
    const result = { ...campaign };

    // Apply updates
    if (input.campaignName !== undefined) {
        result.campaignName = input.campaignName;
    }
    if (input.startDate !== undefined) {
        result.startDate = input.startDate;
    }
    if (input.endDate !== undefined) {
        result.endDate = input.endDate;
    }
    if (input.catalogId !== undefined) {
        result.catalogId = normalizeCatalogId(input.catalogId);
    }
    if (input.isActive !== undefined) {
        result.isActive = input.isActive;
    }

    // Mirror the unitCampaignKey recomputation from request(): whenever any
    // of the key's components change, recompute against the *post-update*
    // values so the response matches what was persisted.
    const hasUnitContext = campaign.unitType !== undefined && campaign.unitNumber !== undefined;
    const componentChanged =
        input.campaignName !== undefined ||
        input.unitType !== undefined ||
        input.unitNumber !== undefined ||
        input.city !== undefined ||
        input.state !== undefined ||
        input.campaignYear !== undefined;
    if (hasUnitContext && componentChanged) {
        result.unitCampaignKey = buildUnitCampaignKey(
            result.unitType,
            result.unitNumber,
            result.city || '',
            result.state || '',
            result.campaignName,
            result.campaignYear
        );
    }

    // Always update updatedAt
    result.updatedAt = util.time.nowISO8601();

    return result;
}
