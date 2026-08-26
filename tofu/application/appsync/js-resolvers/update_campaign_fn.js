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

function hasUnitUpdate(input) {
    return (
        input.unitType !== undefined ||
        input.unitNumber !== undefined ||
        input.city !== undefined ||
        input.state !== undefined
    );
}

function validateUnitUpdate(input, campaign) {
    if (!hasUnitUpdate(input)) {
        return;
    }

    if (campaign.sharedCampaignCode) {
        util.error('Unit information cannot be changed for campaigns created from a shared campaign link.', 'InvalidInput');
        return;
    }

    const unitType = input.unitType !== undefined ? input.unitType : campaign.unitType;
    const unitNumber = input.unitNumber !== undefined ? input.unitNumber : campaign.unitNumber;
    const city = input.city !== undefined ? input.city : campaign.city;
    const state = input.state !== undefined ? input.state : campaign.state;

    if (unitType) {
        if (unitNumber === undefined || unitNumber === null || unitNumber === '') {
            util.error('unitNumber is required when unitType is provided', 'InvalidInput');
            return;
        }
        if (!city) {
            util.error('city is required when unitType is provided', 'InvalidInput');
            return;
        }
        if (!state) {
            util.error('state is required when unitType is provided', 'InvalidInput');
            return;
        }
    }
}

function getUpdatedUnitField(input, campaign, field) {
    return input[field] !== undefined ? input[field] : campaign[field];
}

export function request(ctx) {
    const campaign = ctx.stash.campaign;
    const input = ctx.args.input || ctx.args;

    validateUnitUpdate(input, campaign);

    // Build update expression dynamically
    const updates = [];
    const exprValues = {};
    const exprNames = {};

    const unitType = getUpdatedUnitField(input, campaign, 'unitType');
    const unitNumber = getUpdatedUnitField(input, campaign, 'unitNumber');
    const city = getUpdatedUnitField(input, campaign, 'city');
    const state = getUpdatedUnitField(input, campaign, 'state');
    const campaignName = getUpdatedUnitField(input, campaign, 'campaignName');
    const campaignYear = getUpdatedUnitField(input, campaign, 'campaignYear');

    if (input.campaignName !== undefined) {
        updates.push('campaignName = :campaignName');
        exprValues[':campaignName'] = input.campaignName;
    }
    if (input.campaignYear !== undefined) {
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
    if (input.catalogId !== undefined) {
        updates.push('catalogId = :catalogId');
        // Normalize catalogId to DB format (CATALOG#...)
        exprValues[':catalogId'] = normalizeCatalogId(input.catalogId);
    }
    if (input.isActive !== undefined) {
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
    if (input.city !== undefined) {
        updates.push('city = :city');
        exprValues[':city'] = input.city;
    }
    if (input.state !== undefined) {
        updates.push('state = :state');
        exprValues[':state'] = input.state;
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
            campaignYear,
        );
        updates.push('unitCampaignKey = :unitCampaignKey');
        exprValues[':unitCampaignKey'] = newKey;
    }

    // Recompute unitCampaignKey whenever any of its components change so unit
    // reports/catalogs stay consistent. The key is derived from
    // unitType#unitNumber#city#state#campaignName#campaignYear. Issue #104
    // exposes additional editable fields; future schema changes must extend
    // this guard so the GSI key is never stale. We only emit the SET clause
    // when the campaign already has the unit fields (otherwise the original
    // code did not set a key either). campaignName and campaignYear are
    // handled unconditionally above because they are present in
    // UpdateCampaignInput today; #104 will expand the input shape with the
    // unit fields below.
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

        // Persist any unit field values supplied in the input so the stored
        // fields match the recomputed key. campaignName and campaignYear are
        // already handled above.
        if (input.unitType !== undefined) {
            updates.push('unitType = :unitType');
            exprValues[':unitType'] = input.unitType;
        }
        if (input.unitNumber !== undefined) {
            updates.push('unitNumber = :unitNumber');
            exprValues[':unitNumber'] = input.unitNumber;
        }
        if (input.city !== undefined) {
            updates.push('city = :city');
            exprValues[':city'] = input.city;
        }
        if (input.state !== undefined) {
            updates.push('state = :state');
            exprValues[':state'] = input.state;
        }
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
    if (input.campaignYear !== undefined) {
        result.campaignYear = input.campaignYear;
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
    if (input.unitType !== undefined) {
        result.unitType = input.unitType;
    }
    if (input.unitNumber !== undefined) {
        result.unitNumber = input.unitNumber;
    }
    if (input.city !== undefined) {
        result.city = input.city;
    }
    if (input.state !== undefined) {
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
            campaignYear,
        );
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
        // Apply unit field updates to the result so the recomputed key reflects
        // the post-update state. campaignName and campaignYear are already
        // applied above.
        if (input.unitType !== undefined) {
            result.unitType = input.unitType;
        }
        if (input.unitNumber !== undefined) {
            result.unitNumber = input.unitNumber;
        }
        if (input.city !== undefined) {
            result.city = input.city;
        }
        if (input.state !== undefined) {
            result.state = input.state;
        }

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
