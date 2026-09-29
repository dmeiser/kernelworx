import { describe, it } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildPaymentMethodWrite, mapPaymentMethodWriteError } from './lib/prefs_optimistic_lock.js';

// #531: the #433 optimistic-lock block was copy-pasted into all three
// payment-method resolvers. This test is the regression guard for the
// de-duplication: it fails while the lock is inlined in the resolvers and
// passes once all three delegate to lib/prefs_optimistic_lock.js. The
// per-resolver tests (create_payment_method_fn.test.js,
// update_payment_method_fn.test.js, delete_payment_method_from_prefs_fn.test.js)
// independently pin that the lock is taken on the same conditions as before.
const __dirname = dirname(fileURLToPath(import.meta.url));

const RESOLVERS = [
    'create_payment_method_fn.js',
    'update_payment_method_fn.js',
    'delete_payment_method_from_prefs_fn.js',
];

const LOCK_CONDITION = 'attribute_exists(accountId) AND preferences = :readPrefs';

describe('prefs_optimistic_lock shared helper (#531)', () => {
    it('exposes both helpers so all three resolvers share one lock implementation', () => {
        assert.strictEqual(typeof buildPaymentMethodWrite, 'function');
        assert.strictEqual(typeof mapPaymentMethodWriteError, 'function');
    });

    for (const resolver of RESOLVERS) {
        it(`${resolver} builds its write through lib/prefs_optimistic_lock.js`, () => {
            const source = readFileSync(join(__dirname, resolver), 'utf8');
            assert.match(
                source,
                /from\s+['"]\.\/lib\/prefs_optimistic_lock\.js['"]/,
                `${resolver} must import the shared optimistic-lock helper`,
            );
            assert.doesNotMatch(
                source,
                new RegExp(LOCK_CONDITION.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'),
                `${resolver} must not carry its own copy of the lock condition`,
            );
        });
    }
});
