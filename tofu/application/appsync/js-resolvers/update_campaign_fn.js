import { util } from '@aws-appsync/utils';

function buildUnitCampaignKey(unitType, unitNumber, city, state, campaignName, campaignYear) {
    return [unitType, unitNumber, city, state, campaignName, campaignYear].join('#');
}

function normalizeCatalogId(catalogId) {
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

        // Recompute unitCampaignKey when name changes so unit reports/catalogs stay consistent
        if (campaign.unitType !== undefined && campaign.unitNumber !== undefined) {
            const newKey = buildUnitCampaignKey(
                campaign.unitType,
                campaign.unitNumber,
                campaign.city || '',
                campaign.state || '',
                input.campaignName,
                campaign.campaignYear
            );
            updates.push('unitCampaignKey = :unitCampaignKey');
            exprValues[':unitCampaignKey'] = newKey;
        }
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

        // Mirror the unitCampaignKey recomputation from request()
        if (campaign.unitType !== undefined && campaign.unitNumber !== undefined) {
            result.unitCampaignKey = buildUnitCampaignKey(
                campaign.unitType,
                campaign.unitNumber,
                campaign.city || '',
                campaign.state || '',
                input.campaignName,
                campaign.campaignYear
            );
        }
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

    // Always update updatedAt
    result.updatedAt = util.time.nowISO8601();

    return result;
}
