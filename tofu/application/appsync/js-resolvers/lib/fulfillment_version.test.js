import { describe, it } from 'node:test';
import assert from 'node:assert';
import { fulfillmentVersionGuard, nextFulfillmentVersion, currentFulfillmentVersion } from './fulfillment_version.js';

// The guard is only worth having if the number it pins and the number the write stamps are
// the right pair, so this file checks the pair the way DynamoDB would: by asking whether a
// given row would satisfy the emitted condition, and what version the row carries
// afterwards. `rowSatisfies` mirrors the documented condition semantics -- an equality
// against a missing attribute fails, `attribute_not_exists` succeeds when the row is
// missing, and a condition against a missing item SUCCEEDS unless the expression tests the
// key, which is why every spelling here also tests `attribute_exists(#orderId)`.
function rowSatisfies(guard, row) {
    if (guard.expression.indexOf('attribute_exists(#orderId)') === -1) {
        throw new Error('the guard must require the Order key');
    }
    if (!row) {
        return false;
    }
    const expected = guard.expressionValues[':expectedFulfillmentVersion'];
    const allowsMissing = guard.expression.indexOf('attribute_not_exists(#fulfillmentVersion)') !== -1;
    const actual = Object.hasOwn(row, 'fulfillmentVersion') ? row.fulfillmentVersion : undefined;
    if (actual === undefined) {
        return allowsMissing && expected === 0;
    }
    return actual === expected;
}

describe('nextFulfillmentVersion', () => {
    it('walks 0 -> 1 -> 2 -> 3, which is the sequence every edit and fulfillment must produce', () => {
        let version = 0;
        const seen = [];
        for (let step = 0; step < 3; step = step + 1) {
            version = nextFulfillmentVersion(version);
            seen.push(version);
        }
        assert.deepStrictEqual(seen, [1, 2, 3]);
    });

    it('reads an absent current value as version 0, the pre-Wave-3 spelling', () => {
        assert.strictEqual(nextFulfillmentVersion(undefined), 1);
        assert.strictEqual(nextFulfillmentVersion(null), 1);
        assert.strictEqual(nextFulfillmentVersion(Number.NaN), 1);
    });

    it('refuses a version that is not a number rather than reading it as 0', () => {
        assert.throws(() => nextFulfillmentVersion('7'), /INTERNAL_ERROR/);
        assert.throws(() => nextFulfillmentVersion(true), /INTERNAL_ERROR/);
    });

    it('does not answer 1 for a caller that handed it the row instead of the version', () => {
        // The defect this pins: `nextFulfillmentVersion(order)` silently reads the object
        // as "no version yet" and writes 1 over a row at version 7, moving the
        // serialization point backwards and letting a stale fulfillment through.
        assert.throws(
            () => nextFulfillmentVersion({ fulfillmentVersion: 7 }),
            /INTERNAL_ERROR: fulfillmentVersion must be a number: pass currentFulfillmentVersion\(row\), not the row/
        );
        assert.throws(() => nextFulfillmentVersion('7'), /INTERNAL_ERROR/);
        assert.strictEqual(nextFulfillmentVersion(currentFulfillmentVersion({ fulfillmentVersion: 7 })), 8);
    });
});

describe('currentFulfillmentVersion', () => {
    it('answers 0 for a row that predates the attribute, and for no row at all', () => {
        assert.strictEqual(currentFulfillmentVersion({}), 0);
        assert.strictEqual(currentFulfillmentVersion(null), 0);
        assert.strictEqual(currentFulfillmentVersion({ fulfillmentVersion: 'seven' }), 0);
    });

    it('answers the stored number otherwise', () => {
        assert.strictEqual(currentFulfillmentVersion({ fulfillmentVersion: 0 }), 0);
        assert.strictEqual(currentFulfillmentVersion({ fulfillmentVersion: 4 }), 4);
    });
});

describe('fulfillmentVersionGuard', () => {
    it('lets version 0 match a row that carries no version, and requires the key either way', () => {
        const guard = fulfillmentVersionGuard(0);
        assert.ok(rowSatisfies(guard, { orderId: 'ORDER#o1' }), 'a pre-Wave-3 row is version 0');
        assert.ok(rowSatisfies(guard, { orderId: 'ORDER#o1', fulfillmentVersion: 0 }));
        assert.ok(!rowSatisfies(guard, { orderId: 'ORDER#o1', fulfillmentVersion: 1 }));
        assert.ok(!rowSatisfies(guard, null), 'a deleted Order must not be recreatable by a version-0 write');
    });

    it('refuses a missing version once the caller claims a non-zero one', () => {
        const guard = fulfillmentVersionGuard(2);
        assert.ok(rowSatisfies(guard, { orderId: 'ORDER#o1', fulfillmentVersion: 2 }));
        assert.ok(!rowSatisfies(guard, { orderId: 'ORDER#o1' }));
        assert.ok(!rowSatisfies(guard, { orderId: 'ORDER#o1', fulfillmentVersion: 3 }));
        assert.ok(!rowSatisfies(guard, null), 'a deleted Order must not be writable by any version');
    });

    it('parenthesizes the version test so AND cannot bind it away', () => {
        assert.strictEqual(
            fulfillmentVersionGuard(0).expression,
            '(attribute_not_exists(#fulfillmentVersion) OR #fulfillmentVersion = :expectedFulfillmentVersion) AND attribute_exists(#orderId)'
        );
        assert.strictEqual(
            fulfillmentVersionGuard(5).expression,
            '#fulfillmentVersion = :expectedFulfillmentVersion AND attribute_exists(#orderId)'
        );
    });

    it('serializes a fulfillment racing an edit, in either order', () => {
        // Edit first, then the fulfillment that read the older row: the fulfillment's guard
        // names 1 and the row now says 2, so it fails and the caller re-reads.
        const row = { orderId: 'ORDER#o1', fulfillmentVersion: 0 };
        const editGuard = fulfillmentVersionGuard(currentFulfillmentVersion(row));
        assert.ok(rowSatisfies(editGuard, row));
        row.fulfillmentVersion = nextFulfillmentVersion(currentFulfillmentVersion(row));
        assert.strictEqual(row.fulfillmentVersion, 1);

        const staleFulfillmentGuard = fulfillmentVersionGuard(0);
        assert.ok(!rowSatisfies(staleFulfillmentGuard, row), 'a fulfillment holding version 0 cannot land on a row at 1');

        // Fulfillment first, then the edit that read the older row.
        const other = { orderId: 'ORDER#o2', fulfillmentVersion: 0 };
        other.fulfillmentVersion = nextFulfillmentVersion(currentFulfillmentVersion(other));
        const staleEditGuard = fulfillmentVersionGuard(0);
        assert.ok(!rowSatisfies(staleEditGuard, other), 'an edit holding version 0 cannot land on a row at 1');
    });

    it('lets an edit that read the current row land, and moves the version exactly once', () => {
        const row = { orderId: 'ORDER#o3', fulfillmentVersion: 4 };
        const observed = currentFulfillmentVersion(row);
        const guard = fulfillmentVersionGuard(observed);
        assert.ok(rowSatisfies(guard, row));
        row.fulfillmentVersion = nextFulfillmentVersion(observed);
        assert.strictEqual(row.fulfillmentVersion, 5);
        assert.ok(!rowSatisfies(guard, row), 'the same write cannot land twice on one version');
    });
});
