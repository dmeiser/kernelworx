/**
 * Convert a date input string to an ISO datetime string.
 * Returns empty string for empty/whitespace input.
 * If the value already contains a time portion, it is returned unchanged.
 */
export const dateToISO = (dateString: string): string => {
  if (!dateString || dateString.trim() === '') return '';
  return dateString.includes('T') ? dateString : `${dateString}T00:00:00.000Z`;
};

interface DateParts {
  year: number;
  month: number;
  day: number;
}

const parseDatePart = (dateString: string): DateParts | null => {
  const match = dateString.split('T')[0].match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;

  const year = parseInt(match[1], 10);
  const month = parseInt(match[2], 10);
  const day = parseInt(match[3], 10);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  // Round-trip validation: reject values like 2026-99-99 that Date silently normalizes.
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null;
  }

  return { year, month, day };
};

/**
 * Format an ISO date string for display using only the date part,
 * so "2026-09-01T00:00:00.000Z" renders as "Sep 1, 2026" regardless
 * of the viewer's timezone.
 */
export const formatDisplayDate = (
  dateString: string | undefined | null,
  options?: Intl.DateTimeFormatOptions,
): string => {
  if (!dateString) return '';

  const parts = parseDatePart(dateString);
  if (!parts) return '';

  const date = new Date(parts.year, parts.month - 1, parts.day);
  return date.toLocaleDateString('en-US', options);
};
