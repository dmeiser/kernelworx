import { util } from '@aws-appsync/utils';

// The single definition of the allowed scout unit types. Every resolver that
// writes a unitType (createSellerProfile, updateSellerProfile, updateMyAccount)
// validates through here, so the invariant cannot drift between write paths
// (#520). Keep the list and the error message in sync: the message enumerates
// the sorted list.
export const VALID_UNIT_TYPES = ['Pack', 'Troop', 'Crew', 'Ship', 'Post'];

// Rejects a unit type outside VALID_UNIT_TYPES. No-ops when unitType is absent
// (undefined or null), so callers can invoke it unconditionally.
export function assertValidUnitType(unitType) {
    if (unitType === undefined || unitType === null) {
        return;
    }
    if (!VALID_UNIT_TYPES.includes(unitType)) {
        util.error('unitType must be one of: ' + VALID_UNIT_TYPES.slice().sort().join(', '), 'INVALID_INPUT');
    }
}

// Rejects a unit number that is not a positive integer. No-ops when unitNumber
// is absent (undefined or null).
export function assertValidUnitNumber(unitNumber) {
    if (unitNumber === undefined || unitNumber === null) {
        return;
    }
    if (typeof unitNumber !== 'number' || !Number.isFinite(unitNumber) || Math.floor(unitNumber) !== unitNumber || unitNumber < 1) {
        util.error('unitNumber must be a positive integer', 'INVALID_INPUT');
    }
}
