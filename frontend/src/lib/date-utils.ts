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
  const dateOnly = dateString.split('T')[0];
  const [year, month, day] = dateOnly.split('-').map(Number);
  const parsed = new Date(year, month - 1, day);

  if (
    Number.isNaN(parsed.getTime()) ||
    parsed.getFullYear() !== year ||
    parsed.getMonth() !== month - 1 ||
    parsed.getDate() !== day
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
