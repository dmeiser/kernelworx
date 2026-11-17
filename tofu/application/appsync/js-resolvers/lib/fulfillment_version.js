// The `fulfillmentVersion` guard, spelled the same on both write paths.
//
// Data model §5.19 makes one integer the serialization point for everything that touches
// an Order's fulfillment state: a fulfillment, a reversal, and now a line edit all move
// it, so a concurrent pair of those operations cannot both believe they read the current
// Order. The Python owner of this helper is `fulfillment_version_condition` in
// `src/utils/order_fulfillment_models.py`; this is the APPSYNC_JS side, and the two must
// emit the same condition because they guard the same attribute on the same row.
//
// Two absences have to be told apart, and the expression is the only place that can:
//
//   * A pre-Wave-3 row carries no `fulfillmentVersion` at all, and equality against a
//     missing attribute fails, so version 0 has to match
//     `attribute_not_exists OR attribute = 0` -- both spellings of "nothing has changed
//     this Order's fulfillment state yet".
//   * A row that is not there at all satisfies `attribute_not_exists` too, and a
//     condition against a missing item SUCCEEDS. Without the key test, an UpdateItem
//     would write a partial Order back over a delete that landed after the caller's read
//     -- line items and a version, none of the customer, scope, or totals that made it an
//     Order -- which is the defect `fulfillment_version_condition` documents on the
//     Python side. So every spelling also requires the Order's own key attribute.
//
// The parentheses are required, not stylistic: DynamoDB documents no precedence for
// mixing AND with OR in a condition expression.
export function fulfillmentVersionGuard(expectedVersion) {
    const placeholder = '#fulfillmentVersion';
    const equality = placeholder + ' = :expectedFulfillmentVersion';
    const versionTest = expectedVersion === 0
        ? '(attribute_not_exists(' + placeholder + ') OR ' + equality + ')'
        : equality;
    return {
        expression: versionTest + ' AND attribute_exists(#orderId)',
        expressionNames: { '#fulfillmentVersion': 'fulfillmentVersion', '#orderId': 'orderId' },
        expressionValues: { ':expectedFulfillmentVersion': expectedVersion }
    };
}

// The version a write moves the row to. Absolute rather than `+ :one` because the value
// is already pinned by the condition above: the write cannot land on a row that moved, so
// `expected + 1` is provably the next version when it lands -- and a row that carries no
// attribute at all becomes version 1, which is the number every later read answers.
export function nextFulfillmentVersion(current) {
    const observed = typeof current === 'number' && Number.isFinite(current) ? current : 0;
    return observed + 1;
}

// Reading the attribute off a row that may predate Wave 3. Absent is zero, and zero is
// also what the GraphQL field answers for such a row, so the value the caller was told
// and the value the guard pins are the same number.
export function currentFulfillmentVersion(row) {
    if (!row || typeof row.fulfillmentVersion !== 'number' || !Number.isFinite(row.fulfillmentVersion)) {
        return 0;
    }
    return row.fulfillmentVersion;
}
