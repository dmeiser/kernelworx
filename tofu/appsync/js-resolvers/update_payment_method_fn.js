/**
 * Update payment method name in preferences.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const currentName = ctx.stash.currentName;
    const newName = ctx.stash.newName;
    const methods = ctx.stash.existingMethods || [];

    // If no existing methods, this shouldn't happen (validation should catch it)
    const updated = methods.map(m => {
        if (m.name && m.name.toLowerCase() === currentName.toLowerCase()) {
            return { ...m, name: newName };
        }
        return m;
    });

    const key = { accountId: `ACCOUNT#${accountId}` };
    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues(key),
        update: {
            expression: 'SET #prefs.#pm = :methods',
            expressionNames: {
                '#prefs': 'preferences',
                '#pm': 'paymentMethods'
            },
            expressionValues: util.dynamodb.toMapValues({
                ':methods': updated
            }),
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return { name: ctx.stash.newName, qrCodeUrl: null };
}
