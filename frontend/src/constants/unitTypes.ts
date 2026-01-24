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
