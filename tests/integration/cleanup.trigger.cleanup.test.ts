import { describe, it, expect } from 'vitest';
import globalTeardown from './globalTeardown';

describe('cleanup trigger', () => {
  it('runs the canonical TypeScript cleanup implementation', async () => {
    await globalTeardown();
    expect(true).toBe(true);
  });
});
