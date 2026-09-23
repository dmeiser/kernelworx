/**
 * Remove payment method from preferences array.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const nameLower = ctx.stash.nameLower;
    const methods = ctx.stash.existingMethods || [];
    const readPreferencesExisted = ctx.stash.readPreferencesExisted === true;
    const readPreferences = ctx.stash.readPreferences;

    const updated = methods.filter(m => !m.name || m.name.toLowerCase() !== nameLower);

    const key = { accountId: `ACCOUNT#${accountId}` };

    // Optimistic concurrency: require the account to still exist AND the stored
    // preferences to match the snapshot read by the validation step. This prevents
    // two concurrent mutations from overwriting each other's paymentMethods.
    const conditionExpression = readPreferencesExisted
        ? 'attribute_exists(accountId) AND preferences = :readPrefs'
        : 'attribute_exists(accountId) AND attribute_not_exists(preferences)';

    const conditionValues = {};
    if (readPreferencesExisted) {
        conditionValues[':readPrefs'] = readPreferences;
    }

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
        condition: {
            expression: conditionExpression,
            expressionValues: util.dynamodb.toMapValues(conditionValues)
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Payment methods were modified by another request. Please retry.', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
