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
  const [yearStr, monthStr, dayStr] = dateString.split('T')[0].split('-');
  const year = parseInt(yearStr ?? '', 10);
  const month = parseInt(monthStr ?? '', 10);
  const day = parseInt(dayStr ?? '', 10);
  // If any component is missing or non-numeric, the sum is NaN.
  if (Number.isNaN(year + month + day)) return null;

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
