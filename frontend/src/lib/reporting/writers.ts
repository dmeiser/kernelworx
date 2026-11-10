/**
 * Browser writers for the browser-only reporting engine: CSV, printable
 * HTML, ICS calendar, and the download helper.
 *
 * Requirements: BROWSER_REPORTING_ARCHITECTURE.md §6. Everything is
 * generated locally; no artifact ever touches a server URL. CSV cells
 * reuse the spreadsheet-injection sanitization from lib/reportExport.
 */

import { sanitizeReportValue } from '../reportExport';

// ---------------------------------------------------------------------------
// Download helper
// ---------------------------------------------------------------------------

/**
 * Creates and immediately revokes a browser object URL to trigger a
 * download. No server report URL exists anywhere in this flow.
 */
export function downloadTextFile(fileName: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);
  link.setAttribute('href', url);
  link.setAttribute('download', fileName);
  link.style.visibility = 'hidden';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// CSV writer
// ---------------------------------------------------------------------------

function escapeCsvCell(value: string | number): string {
  const str = String(value);
  return `"${str.replace(/"/g, '""')}"`;
}

/**
 * Rows are already-sanitized cell values (strings/numbers). Header order
 * is caller-defined; every output (screen/CSV/XLSX/print) renders the
 * same rows so totals cannot diverge.
 */
export function toCsv(headers: ReadonlyArray<string>, rows: ReadonlyArray<ReadonlyArray<string | number>>): string {
  const lines = [
    headers.map((h) => escapeCsvCell(sanitizeReportValue(h))),
    ...rows.map((row) => row.map((cell) => escapeCsvCell(sanitizeReportValue(cell)))),
  ];
  return lines.map((line) => line.join(',')).join('\r\n');
}

// ---------------------------------------------------------------------------
// Printable HTML writer
// ---------------------------------------------------------------------------

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export interface PrintableTable {
  title: string;
  headers: ReadonlyArray<string>;
  rows: ReadonlyArray<ReadonlyArray<string | number>>;
  /** Optional summary lines rendered under the table (e.g. totals). */
  summary?: ReadonlyArray<string>;
}

export interface PrintableReport {
  documentTitle: string;
  /** Unit, Unit Campaign, event identity — rendered into the document. */
  scopeLines: ReadonlyArray<string>;
  /** Generation timestamp rendered into the document. */
  generatedAtLabel: string;
  tables: ReadonlyArray<PrintableTable>;
}

/**
 * Generates a self-contained, accessible print-ready HTML document.
 * Printing uses the browser's native print flow; there is no
 * server-generated PDF or HTML payload.
 */
export function buildPrintableHtml(report: PrintableReport): string {
  const scope = report.scopeLines.map((line) => `<div class="scope">${escapeHtml(line)}</div>`).join('');
  const tables = report.tables
    .map((table) => {
      const head = table.headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('');
      const body = table.rows
        .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(String(cell))}</td>`).join('')}</tr>`)
        .join('');
      const summary = table.summary?.length
        ? `<tfoot>${table.summary.map((line) => `<tr><td colspan="${table.headers.length}">${escapeHtml(line)}</td></tr>`).join('')}</tfoot>`
        : '';
      return `<section><h2>${escapeHtml(table.title)}</h2><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody>${summary}</table></section>`;
    })
    .join('');
  return [
    '<!doctype html>',
    '<html lang="en"><head><meta charset="utf-8">',
    `<title>${escapeHtml(report.documentTitle)}</title>`,
    '<style>',
    'body{font-family:system-ui,sans-serif;margin:2rem;color:#111}',
    'h1{font-size:1.25rem}h2{font-size:1rem;margin-top:1.5rem}',
    'table{border-collapse:collapse;width:100%;margin-top:.5rem}',
    'th,td{border:1px solid #999;padding:.3rem .5rem;text-align:left;font-size:.85rem}',
    'thead{display:table-header-group} tfoot td{font-weight:600;border:none}',
    '.scope{margin:.1rem 0;color:#333}.generated-at{color:#555;font-size:.8rem}',
    '</style></head><body>',
    `<h1>${escapeHtml(report.documentTitle)}</h1>`,
    scope,
    `<div class="generated-at">Generated ${escapeHtml(report.generatedAtLabel)}</div>`,
    tables,
    '</body></html>',
  ].join('');
}

// ---------------------------------------------------------------------------
// ICS writer
// ---------------------------------------------------------------------------

export interface IcsEventInput {
  /** Stable identity for the UID (signup/commitment id). */
  uidSeed: string;
  /** Application host, namespacing the UID. */
  host: string;
  summary: string;
  descriptionLines: ReadonlyArray<string>;
  location: string;
  /** ISO 8601 start/end; the writer converts to UTC DTSTART/DTEND. */
  startAt: string;
  endAt: string;
}

/** RFC 5545 TEXT escaping: backslash, semicolon, comma, newlines. */
export function escapeIcsText(value: string): string {
  // Order matters (RFC 5545 §3.3.11): backslash first so the backslashes
  // introduced by the later newline/semicolon/comma escapes are not
  // themselves re-doubled.
  return value.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
}

/** RFC 5545 line folding: physical lines of at most 75 octets. */
export function foldIcsLine(line: string): string {
  const LIMIT = 75;
  if (line.length <= LIMIT) return line;
  const chunks: string[] = [];
  let rest = line;
  chunks.push(rest.slice(0, LIMIT));
  rest = rest.slice(LIMIT);
  while (rest.length > 0) {
    chunks.push(` ${rest.slice(0, LIMIT - 1)}`);
    rest = rest.slice(LIMIT - 1);
  }
  return chunks.join('\r\n');
}

function icsTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`Invalid ICS timestamp: ${iso}`);
  }
  // UTC form: YYYYMMDDTHHMMSSZ — timezone-correct for arbitrary slot durations.
  return date
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}/, '');
}

/**
 * Serializes one VEVENT per selected signup. The file is a snapshot: no
 * subscription, no later update. Caller sets DTSTAMP to generation time.
 */
export function buildIcsCalendar(events: ReadonlyArray<IcsEventInput>, options: { now?: Date } = {}): string {
  const dtstamp = icsTimestamp((options.now ?? new Date()).toISOString());
  const vevents = events.map((event) => {
    const uid = `${encodeURIComponent(event.uidSeed)}@${event.host}`;
    const lines = [
      'BEGIN:VEVENT',
      `UID:${uid}`,
      `DTSTAMP:${dtstamp}`,
      `DTSTART:${icsTimestamp(event.startAt)}`,
      `DTEND:${icsTimestamp(event.endAt)}`,
      `SUMMARY:${escapeIcsText(event.summary)}`,
      `LOCATION:${escapeIcsText(event.location)}`,
      `DESCRIPTION:${escapeIcsText(event.descriptionLines.join('\\n'))}`,
      'END:VEVENT',
    ];
    return lines.map(foldIcsLine).join('\r\n');
  });
  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//kernelworx//show-and-sell//EN',
    ...vevents,
    'END:VCALENDAR',
  ].join('\r\n');
}
