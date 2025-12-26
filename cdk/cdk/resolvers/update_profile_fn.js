import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profile = ctx.stash.profile;
    const input = ctx.args.input;
    const now = util.time.nowISO8601();
    
    // Build update expression dynamically to include optional unit fields
    const expressionParts = ['sellerName = :sellerName', 'updatedAt = :updatedAt'];
    const expressionValues = {
        ':sellerName': input.sellerName,
        ':updatedAt': now
    };
    
    // Add unitType if provided
    if (input.unitType !== undefined && input.unitType !== null) {
        expressionParts.push('unitType = :unitType');
        expressionValues[':unitType'] = input.unitType;
    }
    
    // Add unitNumber if provided
    if (input.unitNumber !== undefined && input.unitNumber !== null) {
        expressionParts.push('unitNumber = :unitNumber');
        expressionValues[':unitNumber'] = input.unitNumber;
    }
    
    // NEW STRUCTURE: Update using ownerAccountId + profileId keys
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ 
        ownerAccountId: profile.ownerAccountId, 
        profileId: input.profileId 
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
    return ctx.result;
}
