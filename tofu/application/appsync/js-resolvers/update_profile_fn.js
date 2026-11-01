import { util } from '@aws-appsync/utils';
import { validateSellerName } from './lib/validate_seller_name.js';
import { validateUnitFields } from './lib/validate_unit_fields.js';

export function request(ctx) {
    const profile = ctx.stash.profile;
    const input = ctx.args.input;
    const now = util.time.nowISO8601();
    const sellerName = validateSellerName(input.sellerName);
    // Rejects invalid unitType/unitNumber up front; only provided fields come back.
    const unitFields = validateUnitFields(input);

    // Build update expression dynamically to include optional unit fields
    const expressionParts = ['sellerName = :sellerName', 'updatedAt = :updatedAt'];
    const expressionValues = {
        ':sellerName': sellerName,
        ':updatedAt': now
    };

    // Add unitType if provided
    if (unitFields.unitType !== undefined) {
        expressionParts.push('unitType = :unitType');
        expressionValues[':unitType'] = unitFields.unitType;
    }

    // Add unitNumber if provided
    if (unitFields.unitNumber !== undefined) {
        expressionParts.push('unitNumber = :unitNumber');
        expressionValues[':unitNumber'] = unitFields.unitNumber;
    }
    
    // NEW STRUCTURE: Update using ownerAccountId + profileId keys
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ 
            ownerAccountId: profile.ownerAccountId, 
            profileId: profile.profileId  // Use profile.profileId which has PROFILE# prefix
        }),
        update: {
            expression: 'SET ' + expressionParts.join(', '),
            expressionValues: util.dynamodb.toMapValues(expressionValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // UpdateItem doesn't return the full item by default, so merge with profile from stash
    const profile = ctx.stash.profile;
    const input = ctx.args.input;
    const now = util.time.nowISO8601();
    
    // Return the updated profile with merged fields. The unit fields reuse the
    // same "provided" rule as request(), so an explicit null keeps the stored
    // value in the response instead of reporting a null that DynamoDB never wrote.
    const unitFields = validateUnitFields(input);
    return {
        ...profile,
        sellerName: validateSellerName(input.sellerName),
        unitType: unitFields.unitType !== undefined ? unitFields.unitType : profile.unitType,
        unitNumber: unitFields.unitNumber !== undefined ? unitFields.unitNumber : profile.unitNumber,
        updatedAt: now
    };
}
