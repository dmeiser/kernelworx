/**
 * Convert a date input string to an ISO datetime string.
 * Returns empty string for empty/whitespace input.
 * If the value already contains a time portion, it is returned unchanged.
 */
export const dateToISO = (dateString: string): string => {
  if (!dateString || dateString.trim() === '') return '';
  return dateString.includes('T') ? dateString : `${dateString}T00:00:00.000Z`;
};
