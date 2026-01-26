/**
 * Fetch payment methods for the profile owner.
 * 
 * Gets custom payment methods from the owner's account preferences.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const ownerAccountId = ctx.stash.ownerAccountId;
    
    if (!ownerAccountId) {
        util.error('Owner account ID not found', 'InternalError');
    }
    
    // ownerAccountId already has 'ACCOUNT#' prefix from the profile
    const key = { accountId: ownerAccountId };
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues(key),
        consistentRead: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Store custom methods in stash for Lambda URL generation
    const account = ctx.result || {};
    ctx.stash.customPaymentMethods = (account.preferences && account.preferences.paymentMethods) || [];
    
    return ctx.stash.customPaymentMethods;
}
