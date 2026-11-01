/**
 * Every verify_profile_owner_for_* resolver must run the shared family spec.
 *
 * A new family member that is not registered in PROFILE_OWNER_FAMILIES would
 * otherwise ship untested, or - the failure this replaced - be given its own
 * hand-written copy of the contract, which then drifts from the other members.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert';
import { readdir } from 'node:fs/promises';

import { PROFILE_OWNER_FAMILIES } from './lib/verify_profile_owner_cases.js';

const FAMILY_MODULE_PREFIX = 'verify_profile_owner_for_';
const FAMILY_MODULE_SUFFIX = '_fn';

describe('verify_profile_owner resolver family', () => {
    it('registers every resolver module in the family', async () => {
        const entries = await readdir(new URL('.', import.meta.url));
        const modules = entries
            .filter((name) => name.startsWith(FAMILY_MODULE_PREFIX) && name.endsWith('_fn.js'))
            .map((name) => name.replace(FAMILY_MODULE_PREFIX, '').replace(/_fn\.js$/, ''))
            .sort();

        assert.deepStrictEqual(
            modules,
            Object.entries(PROFILE_OWNER_FAMILIES)
                .map(([key, family]) => {
                    assert.strictEqual(family.resolver, `${FAMILY_MODULE_PREFIX}${key}${FAMILY_MODULE_SUFFIX}`);
                    return key;
                })
                .sort()
        );
    });
});
