/**
 * Get payment methods preferences for deletion validation.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.identity.sub;
    const name = (ctx.args.name || '').trim();

    if (!accountId) {
        util.error('Authentication required', 'Unauthorized');
    }
    if (!name) {
        util.error('Payment method name is required', 'BadRequest');
    }

    const nameLower = name.toLowerCase();
    if (nameLower === 'cash' || nameLower === 'check') {
        util.error(`Cannot delete reserved payment method '${name}'`, 'BadRequest');
    }

    ctx.stash.accountId = accountId;
    ctx.stash.paymentMethodName = name;
    ctx.stash.nameLower = nameLower;

    const key = { accountId: `ACCOUNT#${accountId}` };
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues(key),
        consistentRead: false,
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const account = ctx.result || {};
    const methods = (account.preferences && account.preferences.paymentMethods) || [];

    const method = methods.find(m => m.name && m.name.toLowerCase() === ctx.stash.nameLower);
    if (!method) {
        util.error(`Payment method '${ctx.stash.paymentMethodName}' not found`, 'NotFound');
    }

    ctx.stash.existingMethods = methods;
    ctx.stash.hasQR = !!(method.qrCodeUrl);
    return {};
}
