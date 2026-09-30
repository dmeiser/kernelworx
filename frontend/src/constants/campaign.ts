export const UNIT_TYPES = [
  { value: '', label: 'None' },
  { value: 'Pack', label: 'Pack (Cub Scouts)' },
  { value: 'Troop', label: 'Troop (Scouts BSA)' },
  { value: 'Crew', label: 'Crew (Venturing)' },
  { value: 'Ship', label: 'Ship (Sea Scouts)' },
  { value: 'Post', label: 'Post (Exploring)' },
  { value: 'Club', label: 'Club (Exploring)' },
];

export const US_STATES = [
  'AL',
  'AK',
  'AZ',
  'AR',
  'CA',
  'CO',
  'CT',
  'DE',
  'FL',
  'GA',
  'HI',
  'ID',
  'IL',
  'IN',
  'IA',
  'KS',
  'KY',
  'LA',
  'ME',
  'MD',
  'MA',
  'MI',
  'MN',
  'MS',
  'MO',
  'MT',
  'NE',
  'NV',
  'NH',
  'NJ',
  'NM',
  'NY',
  'NC',
  'ND',
  'OH',
  'OK',
  'OR',
  'PA',
  'RI',
  'SC',
  'SD',
  'TN',
  'TX',
  'UT',
  'VT',
  'VA',
  'WA',
  'WV',
  'WI',
  'WY',
  'DC',
];

export const CAMPAIGN_OPTIONS = ['Fall', 'Spring', 'Summer', 'Winter'];

/**
 * Bounds for the campaign-year field, and the only rule that decides whether a
 * campaign year is acceptable. Both the Create Campaign and the Create Shared
 * Campaign form read these, so the two cannot drift apart again (issue #539).
 */
export const CAMPAIGN_YEAR_MIN = 2020;

/** Upper bound for the campaign year: a fixed year, not a moving one. */
export const CAMPAIGN_YEAR_MAX = 2050;

/**
 * Whether a campaign year is inside the allowed range. Both create forms gate
 * submission on this, so a year outside the range cannot be submitted even
 * though the number input's `min`/`max` attributes are only advisory.
 */
export const isCampaignYearInRange = (year: number): boolean =>
  Number.isInteger(year) && year >= CAMPAIGN_YEAR_MIN && year <= CAMPAIGN_YEAR_MAX;
