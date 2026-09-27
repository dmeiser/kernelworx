import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');

describe('root package dependency hygiene (#566)', () => {
  it('has no runtime dependencies (dependencies key absent or empty)', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.dependencies ?? {}).toEqual({});
  });

  it('does not install eslint at the root', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.devDependencies?.eslint).toBeUndefined();
  });

  it('does not install jsdom at the root', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.devDependencies?.jsdom).toBeUndefined();
  });

  it('does not install @playwright/mcp anywhere (Playwright runs via Python)', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.devDependencies?.['@playwright/mcp']).toBeUndefined();
    expect(pkg.dependencies?.['@playwright/mcp']).toBeUndefined();
  });

  it('vitest guard suite stays on the node environment (jsdom removal is safe)', () => {
    const config = readFileSync(join(ROOT_DIR, 'vitest.config.ts'), 'utf8');

    const environment = config.match(/environment:\s*['"]([\w-]+)['"]/);
    expect(environment?.[1]).toBe('node');
    expect(config).not.toMatch(/environment:\s*['"](jsdom|happy-dom)['"]/);
  });

  it('lockfile root entry matches package.json', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));
    const lock = JSON.parse(readFileSync(join(ROOT_DIR, 'package-lock.json'), 'utf8'));

    expect(lock.packages?.['']?.devDependencies).toEqual(pkg.devDependencies);
    expect(lock.packages?.['']?.dependencies).toBeUndefined();
  });
});
