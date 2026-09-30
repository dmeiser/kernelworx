import { util } from '@aws-appsync/utils';
import { assertValidUnitType, assertValidUnitNumber } from './lib/unit_fields.js';

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

    assertValidUnitType(input.unitType);
    assertValidUnitNumber(input.unitNumber);

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
