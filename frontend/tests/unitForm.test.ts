/**
 * The Unit form rules (§1.6.1).
 *
 * The generated name and the exact-duplicate key are the two places where the
 * browser and the server must agree without talking to each other: the form shows
 * the name that will be stored, and the diff decides what a save even asks to
 * change. A field missing from the diff cannot be saved, so the table is asserted
 * field by field.
 */

import { describe, expect, it } from 'vitest';
import {
  changedUnitFields,
  emptyUnitForm,
  previewUnitDisplayName,
  unitFormErrors,
  unitFormFromUnit,
} from '../src/lib/unitForm';
import { unitFixture } from './helpers/unitFixtures';

describe('unitFormErrors', () => {
  it('requires geography and a whole unit number, and pre-fills a timezone', () => {
    expect(unitFormErrors(emptyUnitForm())).toEqual({
      unitType: 'Required',
      city: 'Required',
      state: 'Required',
      unitNumber: 'Required',
    });
  });

  it('requires a timezone when the form clears one', () => {
    expect(unitFormErrors({ ...emptyUnitForm(), timezone: '' })).toMatchObject({ timezone: 'Required' });
  });

  it('accepts a complete form', () => {
    const values = { ...emptyUnitForm(), unitType: 'Pack', unitNumber: '3149', city: 'Springfield', state: 'IL' };
    expect(unitFormErrors(values)).toEqual({});
  });

  it('refuses a unit number that is not a positive whole number', () => {
    for (const raw of ['0', '-4', '1.5', 'abc']) {
      expect(unitFormErrors({ ...emptyUnitForm(), unitNumber: raw }).unitNumber).toBe('Enter a whole number');
    }
  });
});

describe('previewUnitDisplayName', () => {
  it('shows the generated name while the display name is left empty', () => {
    const values = { ...emptyUnitForm(), unitType: 'Pack', unitNumber: '3149', city: 'Springfield', state: 'IL' };
    expect(previewUnitDisplayName(values)).toBe('Pack 3149 (Springfield, IL)');
  });

  it('shows the override once one is typed', () => {
    const values = { ...emptyUnitForm(), unitType: 'Pack', unitNumber: '3149', displayName: 'Wolf Pack' };
    expect(previewUnitDisplayName(values)).toBe('Wolf Pack');
  });

  it('stands in for geography that has not been typed yet', () => {
    expect(previewUnitDisplayName(emptyUnitForm())).toBe('Unit 0 (City, ST)');
  });
});

describe('unitFormFromUnit', () => {
  it('reads a stored Unit into the form, treating a null override as empty', () => {
    const values = unitFormFromUnit(unitFixture({ displayName: null }));
    expect(values.unitNumber).toBe('3149');
    expect(values.displayName).toBe('');
    expect(values.timezone).toBe('America/Chicago');
  });
});

describe('changedUnitFields', () => {
  it('sends nothing when the form still matches the stored Unit', () => {
    const unit = unitFixture();
    expect(changedUnitFields(unitFormFromUnit(unit), unit)).toEqual({});
  });

  it('sends only the fields that differ', () => {
    const unit = unitFixture();
    const values = { ...unitFormFromUnit(unit), city: 'Shelbyville', splitDefault: 'TIME_WORKED' } as const;
    expect(changedUnitFields(values, unit)).toEqual({ city: 'Shelbyville', splitDefault: 'TIME_WORKED' });
  });

  it('treats clearing the display name as an edit back to the generated name', () => {
    const unit = unitFixture({ displayName: 'Wolf Pack' });
    const values = { ...unitFormFromUnit(unit), displayName: '' };
    expect(changedUnitFields(values, unit)).toEqual({ displayName: null });
  });

  it('ignores surrounding spaces rather than reporting a change', () => {
    const unit = unitFixture();
    const values = { ...unitFormFromUnit(unit), city: ' Springfield ' };
    expect(changedUnitFields(values, unit)).toEqual({});
  });
});
