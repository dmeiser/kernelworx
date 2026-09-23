/**
 * Update payment method name in preferences.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const currentName = ctx.stash.currentName;
    const newName = ctx.stash.newName;
    const methods = ctx.stash.existingMethods || [];
    const readPreferencesExisted = ctx.stash.readPreferencesExisted === true;
    const readPreferences = ctx.stash.readPreferences;

    // If no existing methods, this shouldn't happen (validation should catch it)
    const updated = methods.map(m => {
        if (m.name && m.name.toLowerCase() === currentName.toLowerCase()) {
            return { ...m, name: newName };
        }
        return m;
    });

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
    return { name: ctx.stash.newName, qrCodeUrl: null };
}
