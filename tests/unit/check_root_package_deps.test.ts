import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');

describe('root package dependency hygiene (#566)', () => {
  it('does not install @playwright/mcp at the root (frontend/ carries its own playwright)', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.dependencies?.['@playwright/mcp']).toBeUndefined();
    expect(pkg.devDependencies?.['@playwright/mcp']).toBeUndefined();
  });
});
