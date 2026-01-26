/**
 * Validate payment method creation request.
 * 
 * Checks:
 * - Name is not empty and max 50 chars
 * - Name is not a reserved name (Cash, Check)
 * - Name is unique for this user (case-insensitive)
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const name = (ctx.args.name || '').trim();
    const accountId = ctx.identity.sub;
    
    if (!accountId) {
        util.error('Authentication required', 'Unauthorized');
    }
    
    // Validate name
    if (!name) {
        util.error('Payment method name is required', 'BadRequest');
    }
    
    if (name.length > 50) {
        util.error('Payment method name must be 50 characters or less', 'BadRequest');
    }
    
    // Check reserved names (case-insensitive)
    const nameLower = name.toLowerCase();
    if (nameLower === 'cash' || nameLower === 'check') {
        util.error(`Cannot create payment method: "${name}" is a reserved name`, 'BadRequest');
    }
    
    // Store normalized name for uniqueness check
    ctx.stash.paymentMethodName = name;
    ctx.stash.paymentMethodNameLower = nameLower;
    ctx.stash.accountId = accountId;
    
    // Fetch existing payment methods to check uniqueness
    const key = { accountId: `ACCOUNT#${accountId}` };
    
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
    
    // Check for duplicate names (case-insensitive)
    const account = ctx.result || {};
    const existingMethods = (account.preferences && account.preferences.paymentMethods) || [];
    const nameLower = ctx.stash.paymentMethodNameLower;
    
    const duplicate = existingMethods.find(m => 
        m.name && m.name.toLowerCase() === nameLower
    );
    
    if (duplicate) {
        util.error(`Payment method "${ctx.stash.paymentMethodName}" already exists`, 'BadRequest');
    }
    
    // Store existing methods for update
    ctx.stash.existingPaymentMethods = existingMethods;
    
    return {};
}
