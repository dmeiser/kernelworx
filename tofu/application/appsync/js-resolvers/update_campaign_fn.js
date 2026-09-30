import { util } from '@aws-appsync/utils';

function buildUnitCampaignKey(unitType, unitNumber, city, state, campaignName, campaignYear) {
    const unitNumStr = '' + unitNumber;
    const yearStr = '' + campaignYear;
    return unitType + '#' + unitNumStr + '#' + (city || '') + '#' + (state || '') + '#' + campaignName + '#' + yearStr;
}

function normalizeCatalogId(catalogId) {
    if (catalogId === null || catalogId === undefined) {
        return null;
    }
    return (typeof catalogId === 'string' && catalogId.startsWith('CATALOG#'))
        ? catalogId
        : 'CATALOG#' + catalogId;
}

function hasUnitUpdate(input) {
    return (
        input.unitType !== undefined ||
        input.unitNumber !== undefined ||
        input.city !== undefined ||
        input.state !== undefined
    );
}

function isNonEmptyUnitField(value) {
    return value !== undefined && value !== null && value !== '';
}

function validateUnitUpdate(input, campaign) {
    if (!hasUnitUpdate(input)) {
        return;
    }

    if (campaign.sharedCampaignCode) {
        util.error('Unit information cannot be changed for campaigns created from a shared campaign link.', 'INVALID_INPUT');
        return;
    }

    const unitType = input.unitType !== undefined ? input.unitType : campaign.unitType;
    const unitNumber = input.unitNumber !== undefined ? input.unitNumber : campaign.unitNumber;
    const city = input.city !== undefined ? input.city : campaign.city;
    const state = input.state !== undefined ? input.state : campaign.state;

    if (unitType) {
        if (!isNonEmptyUnitField(unitNumber)) {
            util.error('unitNumber is required when unitType is provided', 'INVALID_INPUT');
            return;
        }
        if (unitNumber < 1 || Math.floor(unitNumber) !== unitNumber) {
            util.error('unitNumber must be a positive integer', 'INVALID_INPUT');
            return;
        }
        if (!isNonEmptyUnitField(city)) {
            util.error('city is required when unitType is provided', 'INVALID_INPUT');
            return;
        }
        if (!isNonEmptyUnitField(state)) {
            util.error('state is required when unitType is provided', 'INVALID_INPUT');
            return;
        }
    } else if (isNonEmptyUnitField(unitNumber) || isNonEmptyUnitField(city) || isNonEmptyUnitField(state)) {
        util.error('unitType is required when unit fields are present', 'INVALID_INPUT');
        return;
    }
}

function getUpdatedUnitField(input, campaign, field) {
    return input[field] !== undefined ? input[field] : campaign[field];
}

// Fields the Campaign output type declares non-null; an explicit null would
// persist NULL into DynamoDB and make every read of the campaign fail.
const NON_NULLABLE_OUTPUT_FIELDS = ['campaignName', 'campaignYear', 'isActive', 'catalogId'];

function rejectExplicitNulls(input) {
    for (const field of NON_NULLABLE_OUTPUT_FIELDS) {
        // The APPSYNC_JS runtime can surface an omitted nullable input field
        // with a null value, so a value check alone cannot tell an explicit
        // null from an omitted field; key presence can (same contract as
        // #506's update_order_fn / validate_payment_method_fn).
        if (Object.hasOwn(input, field) && input[field] === null) {
            util.error(field + ' cannot be null', 'INVALID_INPUT');
            return;
        }
    }
}

export function request(ctx) {
    const campaign = ctx.stash.campaign;
    const input = ctx.args.input || ctx.args;

    rejectExplicitNulls(input);
    validateUnitUpdate(input, campaign);

    // Build update expression dynamically
    const updates = [];
    const removes = [];
    const exprNames = {};
    const exprValues = {};

    const unitType = getUpdatedUnitField(input, campaign, 'unitType');
    const unitNumber = getUpdatedUnitField(input, campaign, 'unitNumber');
    const city = getUpdatedUnitField(input, campaign, 'city');
    const state = getUpdatedUnitField(input, campaign, 'state');
    const campaignName = getUpdatedUnitField(input, campaign, 'campaignName');
    const campaignYear = getUpdatedUnitField(input, campaign, 'campaignYear');

    // SET branches for non-nullable-output fields also skip a null value: an
    // omitted field can surface as null in this runtime and must leave the
    // stored value untouched (an explicit null was rejected above).
    if (input.campaignName !== undefined && input.campaignName !== null) {
        updates.push('campaignName = :campaignName');
        exprValues[':campaignName'] = input.campaignName;
    }
    if (input.campaignYear !== undefined && input.campaignYear !== null) {
        updates.push('campaignYear = :campaignYear');
        exprValues[':campaignYear'] = input.campaignYear;
    }
    if (input.startDate !== undefined) {
        updates.push('startDate = :startDate');
        exprValues[':startDate'] = input.startDate;
    }
    if (input.endDate !== undefined) {
        updates.push('endDate = :endDate');
        exprValues[':endDate'] = input.endDate;
    }
    if (input.catalogId !== undefined && input.catalogId !== null) {
        updates.push('catalogId = :catalogId');
        // Normalize catalogId to DB format (CATALOG#...)
        exprValues[':catalogId'] = normalizeCatalogId(input.catalogId);
    }
    if (input.isActive !== undefined && input.isActive !== null) {
        updates.push('isActive = :isActive');
        exprValues[':isActive'] = input.isActive;
    }
    if (input.unitType !== undefined) {
        updates.push('unitType = :unitType');
        exprValues[':unitType'] = input.unitType;
    }
    if (input.unitNumber !== undefined) {
        updates.push('unitNumber = :unitNumber');
        exprValues[':unitNumber'] = input.unitNumber;
    }
    // Key presence distinguishes an explicit null (clear the field) from an
    // omitted field, whose value may read as null in this runtime and must
    // not trigger a REMOVE.
    if (Object.hasOwn(input, 'city') && input.city !== null) {
        updates.push('city = :city');
        exprValues[':city'] = input.city;
    } else if (Object.hasOwn(input, 'city') && input.city === null) {
        removes.push('city');
    }
    if (Object.hasOwn(input, 'state') && input.state !== null) {
        updates.push('#state = :state');
        exprNames['#state'] = 'state';
        exprValues[':state'] = input.state;
    } else if (Object.hasOwn(input, 'state') && input.state === null) {
        removes.push('#state');
        exprNames['#state'] = 'state';
    }

    // Recompute unitCampaignKey whenever unit fields, name, or year change and unit info is present
    if (
        (input.campaignName !== undefined ||
            input.campaignYear !== undefined ||
            hasUnitUpdate(input)) &&
        unitType &&
        unitNumber !== undefined &&
        unitNumber !== null &&
        city &&
        state
    ) {
        const newKey = buildUnitCampaignKey(
            unitType,
            unitNumber,
            city,
            state,
            campaignName,
            campaignYear
        );
        updates.push('unitCampaignKey = :unitCampaignKey');
        exprValues[':unitCampaignKey'] = newKey;
    }

    // Remove unitCampaignKey when unit info is cleared so the item no longer
    // appears in unit-scoped queries/reports.
    if (input.unitType !== undefined && input.unitType === null) {
        removes.push('unitCampaignKey');
    }

    // Always update updatedAt
    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();

    if (updates.length === 0 && removes.length === 0) {
        return campaign; // No updates, return original
    }

    let updateExpression = 'SET ' + updates.join(', ');
    if (removes.length > 0) {
        updateExpression += ' REMOVE ' + removes.join(', ');
    }

    const updateObj = {
        expression: updateExpression,
        expressionValues: util.dynamodb.toMapValues(exprValues)
    };
    if (Object.keys(exprNames).length > 0) {
        updateObj.expressionNames = exprNames;
    }

    // V2: Use composite key (profileId, campaignId) - campaignId is the SK
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ profileId: campaign.profileId, campaignId: campaign.campaignId }),
        update: updateObj
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

    // Apply updates. Same presence/null gating as request(): an omitted field
    // can surface as null here and must not overwrite the stored value.
    if (input.campaignName !== undefined && input.campaignName !== null) {
        result.campaignName = input.campaignName;
    }
    if (input.campaignYear !== undefined && input.campaignYear !== null) {
        result.campaignYear = input.campaignYear;
    }
    if (input.startDate !== undefined) {
        result.startDate = input.startDate;
    }
    if (input.endDate !== undefined) {
        result.endDate = input.endDate;
    }
    if (input.catalogId !== undefined && input.catalogId !== null) {
        result.catalogId = normalizeCatalogId(input.catalogId);
    }
    if (input.isActive !== undefined && input.isActive !== null) {
        result.isActive = input.isActive;
    }
    if (input.unitType !== undefined) {
        result.unitType = input.unitType;
    }
    if (input.unitNumber !== undefined) {
        result.unitNumber = input.unitNumber;
    }
    if (Object.hasOwn(input, 'city')) {
        result.city = input.city;
    }
    if (Object.hasOwn(input, 'state')) {
        result.state = input.state;
    }

    // Mirror the unitCampaignKey recomputation from request()
    const unitType = result.unitType;
    const unitNumber = result.unitNumber;
    const city = result.city;
    const state = result.state;
    const campaignName = result.campaignName;
    const campaignYear = result.campaignYear;
    if (
        unitType &&
        unitNumber !== undefined &&
        unitNumber !== null &&
        city &&
        state
    ) {
        result.unitCampaignKey = buildUnitCampaignKey(
            unitType,
            unitNumber,
            city,
            state,
            campaignName,
            campaignYear
        );
    }

    // Remove unitCampaignKey from the response when unit info is cleared.
    if (input.unitType !== undefined && input.unitType === null) {
        result.unitCampaignKey = null;
    }

    // Always update updatedAt
    result.updatedAt = util.time.nowISO8601();

    return result;
}
