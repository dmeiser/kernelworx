import { util } from '@aws-appsync/utils';

function parseIsoToMs(dateStr) {
    if (typeof dateStr !== 'string') {
        return null;
    }
    let s = dateStr;
    if (!s.endsWith('Z') && !s.includes('+') && s.lastIndexOf('-') <= 10) {
        s = s + 'Z';
    }
    const ms = util.time.parseISO8601ToEpochMilliSeconds(s);
    if (ms === null || ms === undefined || isNaN(ms)) {
        return null;
    }
    return ms;
}

export function request(ctx) {
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    const profile = ctx.stash && ctx.stash.profile ? ctx.stash.profile : {};
    const rawProfileId = input.profileId || profile.profileId;
    const dbProfileId = (typeof rawProfileId === 'string' && rawProfileId.startsWith('PROFILE#'))
        ? rawProfileId
        : 'PROFILE#' + rawProfileId;

    const sharedCampaign = ctx.stash && ctx.stash.sharedCampaign;

    let campaignName;
    let campaignYear;
    let rawCatalogId;
    let unitType;
    let unitNumber;
    let city;
    let state;
    let startDate;
    let endDate;
    let sharedCampaignCode;

    if (sharedCampaign) {
        campaignName = sharedCampaign.campaignName;
        campaignYear = sharedCampaign.campaignYear;
        rawCatalogId = sharedCampaign.catalogId;
        unitType = sharedCampaign.unitType;
        unitNumber = sharedCampaign.unitNumber;
        city = sharedCampaign.city;
        state = sharedCampaign.state;
        startDate = (input.startDate !== undefined && input.startDate !== null && input.startDate !== '')
            ? input.startDate
            : sharedCampaign.startDate;
        endDate = (input.endDate !== undefined && input.endDate !== null && input.endDate !== '')
            ? input.endDate
            : sharedCampaign.endDate;
        sharedCampaignCode = input.sharedCampaignCode;
    } else {
        campaignName = input.campaignName;
        campaignYear = input.campaignYear;
        rawCatalogId = input.catalogId;
        unitType = input.unitType;
        unitNumber = input.unitNumber;
        city = input.city;
        state = input.state;
        startDate = input.startDate;
        endDate = input.endDate;
        sharedCampaignCode = null;
    }

    // Required fields validation
    if (!campaignName || (typeof campaignName === 'string' && campaignName.trim() === '')) {
        util.error('campaign_name is required', 'InvalidInput');
    }

    if (campaignYear === undefined || campaignYear === null || campaignYear === '') {
        util.error('campaign_year is required', 'InvalidInput');
    }
    const yearNum = typeof campaignYear === 'number' ? campaignYear : +campaignYear;
    if (isNaN(yearNum) || Math.floor(yearNum) !== yearNum) {
        util.error('campaign_year must be a valid integer', 'InvalidInput');
    }

    if (!rawCatalogId || (typeof rawCatalogId === 'string' && rawCatalogId.trim() === '')) {
        util.error('catalog_id is required', 'InvalidInput');
    }
    const catalogId = (typeof rawCatalogId === 'string' && rawCatalogId.startsWith('CATALOG#'))
        ? rawCatalogId
        : 'CATALOG#' + rawCatalogId;

    // Date range validation
    if (startDate && endDate) {
        if (typeof startDate !== 'string' || typeof endDate !== 'string') {
            util.error('Invalid date format for startDate or endDate', 'InvalidInput');
        }
        const startMs = parseIsoToMs(startDate);
        const endMs = parseIsoToMs(endDate);
        if (startMs === null || endMs === null) {
            util.error('Invalid date format for startDate or endDate', 'InvalidInput');
        }
        if (endMs <= startMs) {
            util.error('endDate must be after startDate', 'InvalidInput');
        }
    } else {
        if (startDate && typeof startDate !== 'string') {
            util.error('Invalid date format for startDate or endDate', 'InvalidInput');
        }
        if (endDate && typeof endDate !== 'string') {
            util.error('Invalid date format for startDate or endDate', 'InvalidInput');
        }
    }

    // Unit fields validation
    let unitCampaignKey = null;
    let validatedUnitNumber = null;
    if (unitType) {
        if (unitNumber === undefined || unitNumber === null || unitNumber === '') {
            util.error('unitNumber is required when unitType is provided', 'InvalidInput');
        }
        const num = typeof unitNumber === 'number' ? unitNumber : +unitNumber;
        if (isNaN(num) || Math.floor(num) !== num) {
            util.error('unitNumber must be a valid integer', 'InvalidInput');
        }
        if (num < 1) {
            util.error('unitNumber must be a positive integer', 'InvalidInput');
        }
        validatedUnitNumber = num;
        if (!city || (typeof city === 'string' && city.trim() === '')) {
            util.error('city is required when unitType is provided', 'InvalidInput');
        }
        if (!state || (typeof state === 'string' && state.trim() === '')) {
            util.error('state is required when unitType is provided', 'InvalidInput');
        }
        unitCampaignKey = unitType + '#' + ('' + validatedUnitNumber) + '#' + city + '#' + state + '#' + campaignName + '#' + ('' + yearNum);
    } else if (
        (unitNumber !== undefined && unitNumber !== null && unitNumber !== '') ||
        (city !== undefined && city !== null && city !== '') ||
        (state !== undefined && state !== null && state !== '')
    ) {
        util.error('unitType is required when unit fields are present', 'InvalidInput');
    }

    const campaignId = 'CAMPAIGN#' + util.autoId();
    const now = util.time.nowISO8601();

    const campaignItem = {
        profileId: dbProfileId,
        campaignId: campaignId,
        campaignName: campaignName,
        campaignYear: yearNum,
        catalogId: catalogId,
        isActive: true,
        createdAt: now,
        updatedAt: now,
    };

    if (startDate) {
        campaignItem.startDate = startDate;
    }
    if (endDate) {
        campaignItem.endDate = endDate;
    }
    if (unitType) {
        campaignItem.unitType = unitType;
        campaignItem.unitNumber = validatedUnitNumber;
        campaignItem.city = city;
        campaignItem.state = state;
        campaignItem.unitCampaignKey = unitCampaignKey;
    }
    if (sharedCampaignCode) {
        campaignItem.sharedCampaignCode = sharedCampaignCode;
    }

    ctx.stash.createdCampaign = campaignItem;

    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({
            profileId: dbProfileId,
            campaignId: campaignId,
        }),
        attributeValues: util.dynamodb.toMapValues(campaignItem),
        condition: {
            expression: 'attribute_not_exists(campaignId)',
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.stash.createdCampaign;
}
