/**
 * Read step of the updateMyPreferences pipeline (#510).
 *
 * Performs a strongly consistent GetItem on the caller's account item and
 * stashes the raw `preferences` snapshot so the write step can apply the same
 * optimistic lock the payment-method mutations use (#433): a preferences
 * write must fail loudly when another request changed the blob after this
 * read, instead of silently deleting keys it never saw (e.g.
 * `paymentMethods` added concurrently).
 */
import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const accountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');

    return {
        operation: 'GetItem',
        consistentRead: true,
        key: util.dynamodb.toMapValues({ accountId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const account = ctx.result || {};
    const readPreferences = account.preferences;
    ctx.stash.readPreferencesExisted = readPreferences !== undefined;
    if (ctx.stash.readPreferencesExisted) {
        ctx.stash.readPreferences = readPreferences;
    }

    // Return the fetched item for observability; the write step only reads the
    // stash, and the pipeline resolver returns the LAST function's result.
    return ctx.result;
}
