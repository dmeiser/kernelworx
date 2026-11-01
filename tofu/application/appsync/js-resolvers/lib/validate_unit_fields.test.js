import { describe, it } from 'node:test';
import assert from 'node:assert';
import { validateUnitFields } from './validate_unit_fields.js';

describe('validateUnitFields', () => {
    it('returns an empty object when neither field is provided', () => {
        assert.deepStrictEqual(validateUnitFields({}), {});
        assert.deepStrictEqual(validateUnitFields({ unitType: undefined, unitNumber: undefined }), {});
    });

    it('skips explicit nulls instead of rejecting them', () => {
        assert.deepStrictEqual(validateUnitFields({ unitType: null, unitNumber: null }), {});
    });

    it('accepts every valid unit type', () => {
        for (const unitType of ['Pack', 'Troop', 'Crew', 'Ship', 'Post']) {
            assert.deepStrictEqual(validateUnitFields({ unitType }), { unitType });
        }
    });

    it('rejects a unit type outside the whitelist', () => {
        assert.throws(
            () => validateUnitFields({ unitType: 'Den' }),
            /INVALID_INPUT: unitType must be one of: Crew, Pack, Post, Ship, Troop/
        );
    });

    it('rejects a unit type that differs only by case or whitespace', () => {
        assert.throws(() => validateUnitFields({ unitType: 'troop' }), /INVALID_INPUT/);
        assert.throws(() => validateUnitFields({ unitType: ' Troop ' }), /INVALID_INPUT/);
    });

    it('rejects an empty-string unit type instead of storing it', () => {
        assert.throws(() => validateUnitFields({ unitType: '' }), /INVALID_INPUT/);
    });

    it('accepts a positive integer unit number', () => {
        assert.deepStrictEqual(validateUnitFields({ unitNumber: 1 }), { unitNumber: 1 });
        assert.deepStrictEqual(validateUnitFields({ unitNumber: 100 }), { unitNumber: 100 });
    });

    it('rejects a non-number unit number', () => {
        assert.throws(() => validateUnitFields({ unitNumber: '42' }), /INVALID_INPUT: unitNumber must be a positive integer/);
    });

    it('rejects zero, negative, fractional, and non-finite unit numbers', () => {
        for (const unitNumber of [0, -3, 1.5, NaN, Infinity]) {
            assert.throws(() => validateUnitFields({ unitNumber }), /INVALID_INPUT: unitNumber must be a positive integer/);
        }
    });

    it('validates both fields in one call', () => {
        assert.deepStrictEqual(
            validateUnitFields({ unitType: 'Ship', unitNumber: 7 }),
            { unitType: 'Ship', unitNumber: 7 }
        );
        assert.throws(
            () => validateUnitFields({ unitType: 'Ship', unitNumber: 0 }),
            /INVALID_INPUT: unitNumber must be a positive integer/
        );
    });
});
