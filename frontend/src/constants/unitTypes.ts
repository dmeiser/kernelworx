/**
 * Unit type constants for Scouting America programs
 */

export interface UnitType {
  value: string;
  label: string;
}

export const UNIT_TYPES: UnitType[] = [
  { value: '', label: 'None' },
  { value: 'Pack', label: 'Pack' },
  { value: 'Troop', label: 'Troop' },
  { value: 'Crew', label: 'Crew' },
  { value: 'Ship', label: 'Ship' },
  { value: 'Post', label: 'Post' },
  { value: 'Club', label: 'Club' },
];

export const UNIT_TYPES_WITHOUT_NONE: UnitType[] = UNIT_TYPES.filter((t) => t.value !== '');

export const SPLIT_DEFAULTS: { value: string; label: string }[] = [
  { value: 'EQUAL', label: 'Split equally' },
  { value: 'TIME_WORKED', label: 'Split by time worked' },
];

export const COUNCIL_BASIS: { value: string; label: string }[] = [
  { value: 'PHYSICAL_STOCK', label: 'Physical stock' },
  { value: 'AFTER_ASSIGNMENTS', label: 'After assignments' },
];
