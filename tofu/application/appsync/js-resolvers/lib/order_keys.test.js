// The ORDER#<campaign without prefix>#<suffix> grammar has one owner (#534):
// buildOrderKey mints it, parseOrderKey reads it back. Both order minters
// (create_order_fn, create_public_order_fn) now call buildOrderKey instead of
// inlining their own concatenation, so this pins the grammar the minters emit
// and the round trip the readers depend on.
import { describe, it } from 'node:test';
import assert from 'node:assert';

import { buildOrderKey, parseOrderKey } from './order_keys.js';

describe('buildOrderKey', () => {
    it('strips the CAMPAIGN# prefix from the campaign half and appends the suffix', () => {
        assert.strictEqual(buildOrderKey('CAMPAIGN#c1', 'uuid-1'), 'ORDER#c1#uuid-1');
    });

    it('passes an already-unprefixed campaign id through untouched', () => {
        assert.strictEqual(buildOrderKey('c1', 'uuid-1'), 'ORDER#c1#uuid-1');
    });

    it('treats a foreign prefix as part of the id rather than stripping it', () => {
        assert.strictEqual(buildOrderKey('PROFILE#c1', 'uuid-1'), 'ORDER#PROFILE#c1#uuid-1');
    });

    it('passes a missing campaign id through as the empty placeholder the minters emitted before #534', () => {
        assert.strictEqual(buildOrderKey(undefined, 'auto-generated-id'), 'ORDER#undefined#auto-generated-id');
    });
});

describe('buildOrderKey / parseOrderKey round trip', () => {
    it('parses back the campaign id and suffix a minter produced', () => {
        const key = buildOrderKey('CAMPAIGN#c1', 'uuid-1');
        assert.deepStrictEqual(parseOrderKey(key), {
            campaignId: 'CAMPAIGN#c1',
            suffix: 'uuid-1',
        });
    });

    it('returns null for a legacy two-part order id', () => {
        assert.strictEqual(parseOrderKey('ORDER#uuid-1'), null);
    });
});
