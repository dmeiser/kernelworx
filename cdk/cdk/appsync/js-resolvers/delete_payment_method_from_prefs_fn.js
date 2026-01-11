/**
 * Remove payment method from preferences array.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const nameLower = ctx.stash.nameLower;
    const methods = ctx.stash.existingMethods || [];

    const updated = methods.filter(m => !m.name || m.name.toLowerCase() !== nameLower);

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
    return true;
}
