/**
 * Validate update payment method request.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.identity.sub;
    const currentName = (ctx.args.currentName || '').trim();
    const newName = (ctx.args.newName || '').trim();

    if (!accountId) {
        util.error('Authentication required', 'UNAUTHORIZED');
    }
    if (!currentName) {
        util.error('Current name is required', 'INVALID_INPUT');
    }
    if (!newName) {
        util.error('New name is required', 'INVALID_INPUT');
    }
    if (newName.length > 50) {
        util.error('Payment method name must be 50 characters or less', 'INVALID_INPUT');
    }
    const newLower = newName.toLowerCase();
    if (newLower === 'cash' || newLower === 'check') {
        util.error(`Cannot rename to reserved method '${newName}'`, 'INVALID_INPUT');
    }

    ctx.stash.accountId = accountId;
    ctx.stash.currentName = currentName;
    ctx.stash.newName = newName;
    ctx.stash.newLower = newLower;

    const key = { accountId: `ACCOUNT#${accountId}` };
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues(key),
        consistentRead: true,
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const account = ctx.result || {};
    const methods = (account.preferences && account.preferences.paymentMethods) || [];

    const exists = methods.find(m => m.name && m.name.toLowerCase() === ctx.stash.currentName.toLowerCase());
    if (!exists) {
        util.error(`Payment method '${ctx.stash.currentName}' not found`, 'NOT_FOUND');
    }

    const duplicate = methods.find(m => m.name && m.name.toLowerCase() === ctx.stash.newLower);
    if (duplicate && ctx.stash.currentName.toLowerCase() !== ctx.stash.newLower) {
        util.error(`Payment method '${ctx.stash.newName}' already exists`, 'INVALID_INPUT');
    }

    ctx.stash.existingMethods = methods;
    return {};
}
