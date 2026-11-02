import { util } from '@aws-appsync/utils';

// Shared unitType/unitNumber validation for the profile create and update paths.
// Absent or explicit-null fields are skipped (they stay out of the returned
// object), so callers write the same "provided" rule in request() and response().
const VALID_UNIT_TYPES = ['Pack', 'Troop', 'Crew', 'Ship', 'Post'];

export function validateUnitFields(input) {
    const source = input || {};
    const validated = {};

    if (source.unitType !== undefined && source.unitType !== null) {
        if (!VALID_UNIT_TYPES.includes(source.unitType)) {
            util.error('unitType must be one of: Crew, Pack, Post, Ship, Troop', 'INVALID_INPUT');
        }
        validated.unitType = source.unitType;
    }

    if (source.unitNumber !== undefined && source.unitNumber !== null) {
        if (
            typeof source.unitNumber !== 'number' ||
            !Number.isFinite(source.unitNumber) ||
            Math.floor(source.unitNumber) !== source.unitNumber ||
            source.unitNumber < 1
        ) {
            util.error('unitNumber must be a positive integer', 'INVALID_INPUT');
        }
        validated.unitNumber = source.unitNumber;
    }

    return validated;
}
