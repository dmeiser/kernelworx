import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');

describe('esbuild dependency pinning (#282)', () => {
  it('pins esbuild to an exact version without semver range specifiers in package.json', () => {
    const pkgPath = join(ROOT_DIR, 'package.json');
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));

    const esbuildVersion = pkg.devDependencies?.esbuild;
    expect(esbuildVersion).toBeDefined();

    // Must be exact semver (e.g. 0.28.2) and not a range like ^0.28.2 or ~0.28.2
    expect(esbuildVersion).toMatch(/^\d+\.\d+\.\d+$/);
    expect(esbuildVersion).not.toMatch(/^[\^~><=]/);
    expect(esbuildVersion).toBe('0.28.2');
  });

  it('pins esbuild to the exact matching version in package-lock.json', () => {
    const lockPath = join(ROOT_DIR, 'package-lock.json');
    const lock = JSON.parse(readFileSync(lockPath, 'utf8'));

    const rootDevDep = lock.packages?.['']?.devDependencies?.esbuild;
    expect(rootDevDep).toBe('0.28.2');

    const nodeModulesPkg = lock.packages?.['node_modules/esbuild'];
    expect(nodeModulesPkg?.version).toBe('0.28.2');
  });
});
