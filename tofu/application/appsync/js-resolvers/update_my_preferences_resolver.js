/**
 * Write step of the updateMyPreferences pipeline (#510).
 *
 * Replaces the caller's `preferences` blob, conditioned on the snapshot the
 * read step stashed (`readPreferences` / `readPreferencesExisted`) so a
 * concurrent write — e.g. a payment-method mutation (#433) — turns into a
 * retryable ConflictException instead of silently deleting keys the caller
 * never saw.
 */
import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const accountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    const preferences = ctx.args.preferences;
    const now = util.time.nowISO8601();
    const readPreferencesExisted = ctx.stash.readPreferencesExisted === true;

    const conditionExpression = readPreferencesExisted
        ? 'attribute_exists(accountId) AND preferences = :readPrefs'
        : 'attribute_exists(accountId) AND attribute_not_exists(preferences)';

    const conditionValues = {};
    if (readPreferencesExisted) {
        conditionValues[':readPrefs'] = ctx.stash.readPreferences;
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ accountId }),
        update: {
            expression: 'SET preferences = :preferences, updatedAt = :updatedAt',
            expressionValues: util.dynamodb.toMapValues({
                ':preferences': preferences,
                ':updatedAt': now
            })
        },
        condition: {
            expression: conditionExpression,
            expressionValues: util.dynamodb.toMapValues(conditionValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Preferences were modified by another request. Please retry.', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
