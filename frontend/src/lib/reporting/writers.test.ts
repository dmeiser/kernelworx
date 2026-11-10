/**
 * Tests for the reporting-engine writers: CSV sanitization, printable
 * HTML escaping, ICS escaping/folding, and the download helper.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { buildIcsCalendar, buildPrintableHtml, downloadTextFile, escapeIcsText, foldIcsLine, toCsv } from './writers';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('toCsv', () => {
  it('quotes cells and escapes embedded quotes', () => {
    const csv = toCsv(['Name', 'Note'], [['Alice', 'said "hi"']]);
    expect(csv).toBe('"Name","Note"\r\n"Alice","said ""hi"""');
  });

  it('sanitizes spreadsheet formula triggers', () => {
    const csv = toCsv(['cmd'], [['=1+1'], ['+SUM(A1)'], ['-2'], ['@ref'], ['\tTAB']]);
    expect(csv).toContain('"\'=1+1"');
    expect(csv).toContain('"\'+SUM(A1)"');
    expect(csv).toContain('"\'-2"');
    expect(csv).toContain('"\'@ref"');
  });
});

describe('buildPrintableHtml', () => {
  it('renders scope identity, generation stamp, and escaped content', () => {
    const html = buildPrintableHtml({
      documentTitle: 'Show & Sell Sales Sheet',
      scopeLines: ['Troop 1 — Fall 2026', 'Event <script>alert(1)</script>'],
      generatedAtLabel: '2026-11-10T12:00:00Z',
      tables: [
        {
          title: 'Sales',
          headers: ['Product', 'Qty'],
          rows: [['Cookies <b>', 3]],
          summary: ['Total $4.05'],
        },
      ],
    });
    expect(html).toContain('Troop 1 — Fall 2026');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('Cookies &lt;b&gt;');
    expect(html).toContain('Generated 2026-11-10T12:00:00Z');
    expect(html).toContain('Total $4.05');
    expect(html).toContain('<thead>'); // repeat header when printed across pages
  });
});

describe('ICS escaping and folding', () => {
  it('escapes commas, semicolons, backslashes, and newlines', () => {
    expect(escapeIcsText('a,b;c\\d\ne')).toBe('a\\,b\\;c\\\\d\\ne');
  });

  it('folds long lines at 75 octets with a leading space continuation', () => {
    const long = `DESCRIPTION:${'x'.repeat(120)}`;
    const folded = foldIcsLine(long);
    const lines = folded.split('\r\n');
    expect(lines[0].length).toBe(75);
    expect(lines[1].startsWith(' ')).toBe(true);
    expect(lines[1].length).toBeLessThanOrEqual(75);
    expect(lines.join('').replace(/^ /, '').length).toBeGreaterThan(0);
  });

  it('leaves short lines untouched', () => {
    expect(foldIcsLine('SUMMARY:Short')).toBe('SUMMARY:Short');
  });
});

describe('buildIcsCalendar', () => {
  it('emits one VEVENT per signup with UTC timestamps and a stable UID', () => {
    const ics = buildIcsCalendar(
      [
        {
          uidSeed: 'signup-42',
          host: 'app.kernelworx.dev',
          summary: 'Show & Sell: Booth 3',
          descriptionLines: ['Troop 1', 'Fall 2026'],
          location: 'Garage, 123 Main St',
          startAt: '2026-12-05T18:30:00-05:00',
          endAt: '2026-12-05T20:30:00-05:00',
        },
      ],
      { now: new Date('2026-11-10T12:00:00Z') },
    );
    expect(ics.startsWith('BEGIN:VCALENDAR')).toBe(true);
    expect(ics.trimEnd().endsWith('END:VCALENDAR')).toBe(true);
    expect(ics).toContain('UID:signup-42@app.kernelworx.dev');
    expect(ics).toContain('DTSTAMP:20261110T120000Z');
    expect(ics).toContain('DTSTART:20261205T233000Z'); // -05:00 converted to UTC
    expect(ics).toContain('DTEND:20261206T013000Z');
    expect(ics).toContain('SUMMARY:Show & Sell: Booth 3');
    expect(ics.match(/BEGIN:VEVENT/g)).toHaveLength(1);
  });

  it('rejects invalid timestamps loudly', () => {
    expect(() =>
      buildIcsCalendar([
        {
          uidSeed: 's',
          host: 'h',
          summary: 'x',
          descriptionLines: [],
          location: 'y',
          startAt: 'not-a-date',
          endAt: '2026-12-05T20:30:00Z',
        },
      ]),
    ).toThrow(/Invalid ICS timestamp/);
  });

  it('strips injection attempts via escaping, never raw newlines in values', () => {
    const ics = buildIcsCalendar([
      {
        uidSeed: 's',
        host: 'h',
        summary: 'Booth\nATTENDEE:evil@example.com',
        descriptionLines: ['line1', 'line2'],
        location: 'loc',
        startAt: '2026-12-05T18:30:00Z',
        endAt: '2026-12-05T20:30:00Z',
      },
    ]);
    // The raw newline inside the summary value must be escaped, so a
    // literal "ATTENDEE:" line can never appear from user text.
    expect(ics).not.toContain('\nATTENDEE');
    expect(ics).toContain('Booth\\nATTENDEE:evil@example.com');
  });
});

describe('downloadTextFile', () => {
  it('creates and revokes an object URL without any server URL', () => {
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadTextFile('report.csv', 'a,b', 'text/csv');
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
    expect(click).toHaveBeenCalledOnce();
  });
});
