import { util } from '@aws-appsync/utils';

export function request(ctx) {
    if (!ctx.identity || !ctx.identity.sub) {
        util.error('Authentication required', 'UNAUTHORIZED');
    }

    const input = ctx.args.input || {};

    const sellerName = input.sellerName ? input.sellerName.trim() : '';
    if (!sellerName) {
        util.error('sellerName is required', 'INVALID_INPUT');
    }
    if ([...sellerName].length > 100) {
        util.error('sellerName cannot exceed 100 characters', 'INVALID_INPUT');
    }

    const validUnitTypes = ['Pack', 'Troop', 'Crew', 'Ship', 'Post'];
    if (input.unitType !== undefined && input.unitType !== null) {
        if (!validUnitTypes.includes(input.unitType)) {
            util.error('unitType must be one of: Crew, Pack, Post, Ship, Troop', 'INVALID_INPUT');
        }
    }

    if (input.unitNumber !== undefined && input.unitNumber !== null) {
        if (typeof input.unitNumber !== 'number' || !Number.isFinite(input.unitNumber) || Math.floor(input.unitNumber) !== input.unitNumber || input.unitNumber < 1) {
            util.error('unitNumber must be a positive integer', 'INVALID_INPUT');
        }
    }

    const profileId = 'PROFILE#' + util.autoId();
    const ownerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    const now = util.time.nowISO8601();

    const item = {
        ownerAccountId: ownerAccountId,
        profileId: profileId,
        sellerName: sellerName,
        createdAt: now,
        updatedAt: now,
    };
    if (input.unitType) {
        item.unitType = input.unitType;
    }
    if (input.unitNumber !== undefined && input.unitNumber !== null) {
        item.unitNumber = input.unitNumber;
    }

    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({
            ownerAccountId: ownerAccountId,
            profileId: profileId,
        }),
        attributeValues: util.dynamodb.toMapValues(item),
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
