/**
 * Create payment method in DynamoDB.
 * 
 * Adds the new payment method to the user's preferences.paymentMethods array.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const methodName = ctx.stash.paymentMethodName;
    const existingMethods = ctx.stash.existingPaymentMethods || [];
    const readPreferencesExisted = ctx.stash.readPreferencesExisted === true;
    const readPreferences = ctx.stash.readPreferences;

    // Create new payment method object
    const newMethod = {
        name: methodName,
        qrCodeUrl: null  // No QR code initially
    };
    
    // Add to existing methods array
    const updatedMethods = [...existingMethods, newMethod];
    
    // Update preferences.paymentMethods in the account item
    const key = {
        accountId: `ACCOUNT#${accountId}`
    };
    
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
                ':methods': updatedMethods
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
            util.error('Payment methods were modified by another request. Please retry.', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Return the created payment method
    return {
        name: ctx.stash.paymentMethodName,
        qrCodeUrl: null
    };
}
