import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const accountId = 'ACCOUNT#' + ctx.identity.sub;
    // AWSJSON arrives as a string, but the stored `preferences` attribute is a
    // DynamoDB map (payment methods live under preferences.paymentMethods), so
    // parse before writing to keep the attribute shape stable (#510).
    const preferences = JSON.parse(ctx.args.preferences);
    const expectedPreferences = ctx.args.expectedPreferences;
    const now = util.time.nowISO8601();

    // Optimistic lock (#510): the write only lands when the stored blob still
    // matches the snapshot the caller read (same conditional-write pattern as
    // the payment-method mutations, #433). The snapshot may be stored either
    // as a map (current writers after #510) or as a raw JSON string (legacy
    // rows from the pre-#510 resolver and AWSJSON results still cached on the
    // client), so the equality is satisfied by EITHER shape; a concurrent
    // write of either shape changes the stored value and fails both. With no
    // snapshot, only a first write may create the attribute — a missing or
    // stale snapshot fails loudly instead of silently discarding a concurrent
    // update (for example a payment-method write) the caller never saw.
    // An explicit null is not the same as omitting the field: only omission
    // means "no snapshot read yet" (first-write semantics). A caller passing
    // null explicitly is masking a bug, so reject it loudly.
    if (expectedPreferences === null) {
        util.error('expectedPreferences must be a JSON string or omitted, not null', 'INVALID_INPUT');
    }

    const conditionValues = {};
    let conditionExpression;
    if (expectedPreferences) {
        conditionExpression =
            'attribute_exists(accountId) AND (preferences = :readPrefsMap OR preferences = :readPrefsStr)';
        conditionValues[':readPrefsMap'] = JSON.parse(expectedPreferences);
        conditionValues[':readPrefsStr'] = expectedPreferences;
    } else {
        conditionExpression = 'attribute_exists(accountId) AND attribute_not_exists(preferences)';
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ accountId: accountId }),
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
            // Retryable: the stored blob changed (or the account/preferences
            // state no longer matches the caller's snapshot). The caller must
            // re-read and retry rather than overwrite someone else's write.
            util.error('Preferences were modified by another request. Please refresh and retry.', 'ConflictException');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
