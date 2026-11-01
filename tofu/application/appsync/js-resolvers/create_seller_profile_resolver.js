import { util } from '@aws-appsync/utils';
import { validateSellerName } from './lib/validate_seller_name.js';
import { validateUnitFields } from './lib/validate_unit_fields.js';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    if (!ctx.identity || !ctx.identity.sub) {
        util.error('Authentication required', 'UNAUTHORIZED');
    }

    const input = ctx.args.input || {};

    const sellerName = validateSellerName(input.sellerName);
    const unitFields = validateUnitFields(input);

    const profileId = 'PROFILE#' + util.autoId();
    const ownerAccountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    const now = util.time.nowISO8601();

    const item = {
        ownerAccountId: ownerAccountId,
        profileId: profileId,
        sellerName: sellerName,
        createdAt: now,
        updatedAt: now,
    };
    if (unitFields.unitType !== undefined) {
        item.unitType = unitFields.unitType;
    }
    if (unitFields.unitNumber !== undefined) {
        item.unitNumber = unitFields.unitNumber;
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
