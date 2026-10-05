/**
 * Unit tests for the QR decoded-link allowlist.
 *
 * This is a pure function precisely so the scheme rules can be pinned here:
 * the browser path cannot cheaply inject a QR into a real image, and the
 * security-relevant decision (render a link or not) does not depend on the
 * canvas plumbing at all.
 */

import { describe, it, expect } from 'vitest';
import { ALLOWED_QR_LINK_PROTOCOLS, MAX_QR_LINK_LENGTH, sanitizeQrLink } from '../../src/lib/qrLinkSafety';

describe('sanitizeQrLink', () => {
  it('accepts https links', () => {
    expect(sanitizeQrLink('https://pay.example.com/invoice/123')).toBe('https://pay.example.com/invoice/123');
  });

  it('accepts mailto links', () => {
    expect(sanitizeQrLink('mailto:seller@example.com?subject=Order')).toBe('mailto:seller@example.com?subject=Order');
  });

  it('trims surrounding whitespace before deciding', () => {
    expect(sanitizeQrLink('  https://pay.example.com/a  ')).toBe('https://pay.example.com/a');
  });

  it('normalizes the rendered href instead of echoing the raw payload', () => {
    // Tabs and newlines are stripped by the URL parser; echoing the raw string
    // could render a different target than the one that was checked.
    expect(sanitizeQrLink('https://pay.example.com/a\tb')).toBe('https://pay.example.com/ab');
  });

  it.each([
    ['http downgrade', 'http://pay.example.com/invoice'],
    ['script scheme', 'javascript:alert(1)'],
    ['uppercase script scheme', 'JavaScript:alert(document.cookie)'],
    ['inline data', 'data:text/html,<script>alert(1)</script>'],
    ['local file', 'file:///etc/passwd'],
    ['protocol relative', '//evil.tld/pay'],
    ['relative path', '/o/profile/token'],
    ['bare word', 'pay.example.com'],
    ['scheme-less with port', 'evil.tld:8080/x'],
  ])('rejects %s with no rendered link', (_label, payload) => {
    expect(sanitizeQrLink(payload)).toBeNull();
  });

  it('rejects empty, whitespace-only, null and undefined payloads', () => {
    expect(sanitizeQrLink('')).toBeNull();
    expect(sanitizeQrLink('   ')).toBeNull();
    expect(sanitizeQrLink(null)).toBeNull();
    expect(sanitizeQrLink(undefined)).toBeNull();
  });

  it('rejects non-string payloads', () => {
    expect(sanitizeQrLink(42 as unknown as string)).toBeNull();
    expect(sanitizeQrLink({ url: 'https://x.example' } as unknown as string)).toBeNull();
  });

  it('rejects payloads over the length bound', () => {
    const long = `https://pay.example.com/${'a'.repeat(MAX_QR_LINK_LENGTH)}`;
    expect(long.length).toBeGreaterThan(MAX_QR_LINK_LENGTH);
    expect(sanitizeQrLink(long)).toBeNull();
  });

  it('accepts a payload at exactly the length bound', () => {
    const exact = `https://pay.example.com/${'a'.repeat(MAX_QR_LINK_LENGTH - 'https://pay.example.com/'.length)}`;
    expect(exact.length).toBe(MAX_QR_LINK_LENGTH);
    expect(sanitizeQrLink(exact)).toBe(exact);
  });

  it('keeps the allowlist to https and mailto only', () => {
    expect(ALLOWED_QR_LINK_PROTOCOLS).toEqual(['https:', 'mailto:']);
  });
});
