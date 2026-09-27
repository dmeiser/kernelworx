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

  it('does not install eslint at the root (no root lint script invokes it)', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.devDependencies?.eslint).toBeUndefined();
    expect(pkg.scripts?.lint).toBeUndefined();
  });

  it('does not install jsdom at the root (guard suite runs with environment: node)', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.devDependencies?.jsdom).toBeUndefined();
  });

  it('does not install @playwright/mcp anywhere (Playwright runs via Python)', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));

    expect(pkg.devDependencies?.['@playwright/mcp']).toBeUndefined();
    expect(pkg.dependencies?.['@playwright/mcp']).toBeUndefined();
  });

  it('lockfile root entry matches package.json and stays free of the removed packages', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT_DIR, 'package.json'), 'utf8'));
    const lock = JSON.parse(readFileSync(join(ROOT_DIR, 'package-lock.json'), 'utf8'));

    expect(lock.packages?.['']?.devDependencies).toEqual(pkg.devDependencies);
    expect(lock.packages?.['']?.dependencies).toBeUndefined();

    const removed = ['node_modules/eslint', 'node_modules/jsdom', 'node_modules/@playwright/mcp'];
    for (const name of removed) {
      expect(lock.packages?.[name]).toBeUndefined();
    }
  });
});
