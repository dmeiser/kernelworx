import { describe, it, expect } from 'vitest';
import { isDevelopment, getVersionString, getBuildTimeUTC } from '../src/lib/buildInfo';

describe('buildInfo', () => {
  it('evaluates development status', () => {
    expect(typeof isDevelopment()).toBe('boolean');
  });
  it('formats version string', () => {
    expect(getVersionString()).toContain('v');
  });
  it('formats build time utc', () => {
    expect(getBuildTimeUTC()).toContain('UTC');
  });
});
