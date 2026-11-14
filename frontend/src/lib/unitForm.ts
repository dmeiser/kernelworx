/**
 * The Unit form as data: its shape, its validation, and the diff a save sends.
 *
 * This lives apart from the form component for two reasons. The rules are shared
 * by the create dialog and the settings screen, and a rule duplicated between them
 * eventually differs — usually in the direction of one screen accepting something
 * the server then refuses. And the diff decides what `updateUnit` is even asked to
 * change: sending the whole record would let a screen that rendered a stale Unit
 * quietly write another admin's values back.
 */

import { unitDisplayName } from './units';
import type { GqlCouncilNeedBasis, GqlSplitMethod, GqlUnit } from '../types/graphql-generated';

export interface UnitFormValues {
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  displayName: string;
  timezone: string;
  splitDefault: GqlSplitMethod;
  councilNeedBasis: GqlCouncilNeedBasis;
}

export function emptyUnitForm(): UnitFormValues {
  return {
    unitType: '',
    unitNumber: '',
    city: '',
    state: '',
    displayName: '',
    timezone: 'America/Chicago',
    splitDefault: 'EQUAL',
    councilNeedBasis: 'PHYSICAL_STOCK',
  };
}

export function unitFormFromUnit(unit: GqlUnit): UnitFormValues {
  return {
    unitType: unit.unitType,
    unitNumber: String(unit.unitNumber),
    city: unit.city,
    state: unit.state,
    displayName: unit.displayName ?? '',
    timezone: unit.timezone,
    splitDefault: unit.splitDefault,
    councilNeedBasis: unit.councilNeedBasis,
  };
}

/** Fields whose empty value is a mistake rather than a choice. */
const REQUIRED_TEXT_FIELDS: ReadonlyArray<keyof UnitFormValues> = ['unitType', 'city', 'state', 'timezone'];

function unitNumberError(raw: string): string | undefined {
  if (!raw.trim()) return 'Required';
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 1) return 'Enter a whole number';
  return undefined;
}

/** Field-level problems, keyed by field; an empty object means the form may submit. */
export function unitFormErrors(values: UnitFormValues): Partial<Record<keyof UnitFormValues, string>> {
  const errors: Partial<Record<keyof UnitFormValues, string>> = {};
  for (const field of REQUIRED_TEXT_FIELDS) {
    if (!String(values[field]).trim()) errors[field] = 'Required';
  }
  const numberError = unitNumberError(values.unitNumber);
  if (numberError) errors.unitNumber = numberError;
  return errors;
}

/** The name this form would produce, shown before the admin commits to one.
 *  The placeholders stand in only until a field is typed — the server's own
 *  fallback is the one that gets stored, and it is the same rule. */
export function previewUnitDisplayName(values: UnitFormValues): string {
  return unitDisplayName({
    unitType: values.unitType.trim() || 'Unit',
    unitNumber: Number(values.unitNumber) || 0,
    city: values.city.trim() || 'City',
    state: values.state.trim() || 'ST',
    displayName: values.displayName,
  });
}

/**
 * One field the edit screen can change, described by how to read it from the form
 * and from the stored Unit. A table rather than a chain of comparisons keeps the
 * two screens reading the same list, and a field missing here is a field no save
 * can send — which is the safe direction for a mistake.
 */
interface UnitFieldRule {
  key: string;
  fromForm: (values: UnitFormValues) => unknown;
  fromUnit: (unit: GqlUnit) => unknown;
}

const UNIT_FIELD_RULES: ReadonlyArray<UnitFieldRule> = [
  { key: 'unitType', fromForm: (values) => values.unitType.trim(), fromUnit: (unit) => unit.unitType },
  { key: 'unitNumber', fromForm: (values) => Number(values.unitNumber), fromUnit: (unit) => unit.unitNumber },
  { key: 'city', fromForm: (values) => values.city.trim(), fromUnit: (unit) => unit.city },
  { key: 'state', fromForm: (values) => values.state.trim(), fromUnit: (unit) => unit.state },
  {
    key: 'displayName',
    // Clearing the override is a real edit: null means "use the generated name",
    // which is not the same as leaving the field out of the request.
    fromForm: (values) => values.displayName.trim() || null,
    fromUnit: (unit) => unit.displayName ?? null,
  },
  { key: 'timezone', fromForm: (values) => values.timezone, fromUnit: (unit) => unit.timezone },
  { key: 'splitDefault', fromForm: (values) => values.splitDefault, fromUnit: (unit) => unit.splitDefault },
  {
    key: 'councilNeedBasis',
    fromForm: (values) => values.councilNeedBasis,
    fromUnit: (unit) => unit.councilNeedBasis,
  },
];

/** The fields that actually differ from what was read; empty means nothing to save. */
export function changedUnitFields(values: UnitFormValues, unit: GqlUnit): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  for (const rule of UNIT_FIELD_RULES) {
    const next = rule.fromForm(values);
    if (!Object.is(next, rule.fromUnit(unit))) changes[rule.key] = next;
  }
  return changes;
}

/**
 * The `createUnit` body.
 *
 * Built here rather than inline in the dialog so the payload contract — trimmed
 * geography, a number not a string, an empty override sent as null so the server
 * stores the generated name, and one idempotency key per intent — has one home
 * and can be asserted directly.
 */
export function createUnitInput(values: UnitFormValues, idempotencyKey: string, duplicateConfirmed: boolean): Record<string, unknown> {
  return {
    unitType: values.unitType.trim(),
    unitNumber: Number(values.unitNumber),
    city: values.city.trim(),
    state: values.state.trim(),
    timezone: values.timezone,
    splitDefault: values.splitDefault,
    councilNeedBasis: values.councilNeedBasis,
    // An empty override is sent as null, not omitted: the server then stores the
    // generated name the form already previewed.
    displayName: values.displayName.trim() || null,
    duplicateConfirmed,
    idempotency: { idempotencyKey },
  };
}
