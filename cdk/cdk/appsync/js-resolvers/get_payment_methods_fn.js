/**
 * Fetch payment methods from user preferences in DynamoDB.
 * 
 * This function retrieves custom payment methods for the authenticated user.
 * Global methods (cash, check) are NOT stored and will be injected later.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.identity.sub;
    
    if (!accountId) {
        util.error('Authentication required', 'Unauthorized');
    }
    
    // Account table uses accountId as primary key (with ACCOUNT# prefix)
    const key = {
        accountId: `ACCOUNT#${accountId}`
    };
    
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
    
    // Extract payment methods from preferences.paymentMethods
    const account = ctx.result || {};
    const prefs = account.preferences || {};
    const paymentMethods = prefs.paymentMethods || [];
    
    ctx.stash.customPaymentMethods = paymentMethods;
    
    return paymentMethods;
}
