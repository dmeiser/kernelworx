/**
 * Tests for date utility helpers.
 */

import { describe, it, expect } from 'vitest';
import { dateToISO, formatDisplayDate } from '../../src/lib/date-utils';

describe('dateToISO', () => {
  it('returns empty string for empty or whitespace input', () => {
    expect(dateToISO('')).toBe('');
    expect(dateToISO('   ')).toBe('');
  });

  it('returns the value unchanged when it already contains a time portion', () => {
    const iso = '2025-03-01T12:30:00.000Z';
    expect(dateToISO(iso)).toBe(iso);
  });

  it('appends UTC midnight to a date-only string', () => {
    expect(dateToISO('2025-03-01')).toBe('2025-03-01T00:00:00.000Z');
  });
});

describe('formatDisplayDate', () => {
  it('returns empty string for null, undefined, or empty input', () => {
    expect(formatDisplayDate(null)).toBe('');
    expect(formatDisplayDate(undefined)).toBe('');
    expect(formatDisplayDate('')).toBe('');
  });

  it('returns empty string for malformed date strings', () => {
    expect(formatDisplayDate('not-a-date')).toBe('');
    expect(formatDisplayDate('2025/03/01')).toBe('');
  });

  it('returns empty string for out-of-range date components', () => {
    expect(formatDisplayDate('2026-99-99')).toBe('');
    expect(formatDisplayDate('2026-09-31')).toBe('');
    expect(formatDisplayDate('2026-00-15')).toBe('');
    expect(formatDisplayDate('2026-13-01')).toBe('');
  });

  it('renders UTC midnight dates using the date part only', () => {
    expect(formatDisplayDate('2026-09-01T00:00:00.000Z')).toBe('9/1/2026');
  });

  it('ignores the time portion and uses the date part', () => {
    expect(formatDisplayDate('2026-09-01T23:59:59.000Z')).toBe('9/1/2026');
  });

  it('honors Intl.DateTimeFormat options', () => {
    expect(
      formatDisplayDate('2026-09-01T00:00:00.000Z', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }),
    ).toBe('September 1, 2026');
  });
});
