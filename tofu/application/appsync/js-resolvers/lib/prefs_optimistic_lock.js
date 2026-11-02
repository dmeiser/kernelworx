/**
 * Shared optimistic-concurrency helper for the payment-method preferences
 * writes (#433). The create, update, and delete payment-method resolvers all
 * read-modify-write `preferences.paymentMethods` on the account item, and each
 * must take the same condition against the snapshot the validation step read,
 * so that two concurrent mutations cannot silently overwrite each other's
 * paymentMethods. Kept in lib/ so the lock is a single editable artifact and
 * the same shape unit-testable without rendering Terraform.
 */
import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './ids.js';

/**
 * Build the UpdateItem request for a `preferences.paymentMethods` write.
 *
 * The condition requires the account to still exist AND the stored
 * preferences to match the snapshot read by the validation step
 * (`readPreferencesExisted`/`readPreferences` are stashed by the
 * validation step; `updatedMethods` is the new array computed by the caller).
 */
export function buildPaymentMethodWrite(accountId, readPreferencesExisted, readPreferences, updatedMethods) {
    const conditionExpression = readPreferencesExisted
        ? 'attribute_exists(accountId) AND preferences = :readPrefs'
        : 'attribute_exists(accountId) AND attribute_not_exists(preferences)';

    const conditionValues = {};
    if (readPreferencesExisted) {
        conditionValues[':readPrefs'] = readPreferences;
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ accountId: normalizeIdOrPrefix(accountId, 'ACCOUNT#') }),
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

/**
 * Map the DynamoDB conditional-check failure raised when the optimistic
 * condition no longer holds to a retryable ConflictException, and re-throw
 * any other error unchanged. Throws; does not return on the error path.
 */
export function mapPaymentMethodWriteError(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            util.error('Payment methods were modified by another request. Please retry.', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
}
