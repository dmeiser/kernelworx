import { describe, it, expect } from 'vitest';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');
const SCRIPT = join(ROOT_DIR, 'scripts', 'build-resolvers.mjs');
const REL_SRC = join('tofu', 'application', 'appsync', 'js-resolvers');
const REL_DIST = join('tofu', 'application', 'appsync', 'dist');

interface RunResult {
    status: number | null;
    stdout: string;
    stderr: string;
}

function runNode(script: string, cwd: string): RunResult {
    try {
        const stdout = execFileSync('node', [script], { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
        return { status: 0, stdout, stderr: '' };
    } catch (err) {
        const e = err as { status?: number | null; stdout?: string; stderr?: string };
        return { status: e.status ?? null, stdout: e.stdout ?? '', stderr: e.stderr ?? '' };
    }
}

describe('scripts/build-resolvers.mjs (#281)', () => {
    it('resolves paths relative to the script, not cwd', () => {
        // /tmp is outside the repo, so cwd-relative paths would fail here.
        const result = runNode(SCRIPT, tmpdir());
        expect(result.status).toBe(0);
        expect(result.stdout).toContain('Resolvers bundled successfully');
        expect(existsSync(join(ROOT_DIR, REL_DIST))).toBe(true);
    });

    it('does not delete the previous bundle when the source dir is missing', () => {
        // Fixture must live inside the repo so `import 'esbuild'` resolves.
        const fixture = mkdtempSync(join(ROOT_DIR, '.tmp-build-resolvers-'));
        try {
            mkdirSync(join(fixture, 'scripts'), { recursive: true });
            mkdirSync(join(fixture, REL_DIST), { recursive: true });
            copyFileSync(SCRIPT, join(fixture, 'scripts', 'build-resolvers.mjs'));
            const sentinel = join(fixture, REL_DIST, 'bundle.js');
            writeFileSync(sentinel, '// last good bundle');

            const result = runNode(join(fixture, 'scripts', 'build-resolvers.mjs'), fixture);
            expect(result.status).not.toBe(0);
            expect(result.stderr).toContain('js-resolvers');
            // The previous bundle must survive the failed run.
            expect(existsSync(sentinel)).toBe(true);
            expect(readFileSync(sentinel, 'utf8')).toBe('// last good bundle');
        } finally {
            rmSync(fixture, { recursive: true, force: true });
        }
    });

    it('fails with an explicit npm ci message when esbuild is missing', () => {
        // Outside the repo, `import 'esbuild'` cannot resolve — simulates
        // running before `npm ci` at the repo root.
        const fixture = mkdtempSync(join(tmpdir(), 'kw-build-resolvers-'));
        try {
            mkdirSync(join(fixture, 'scripts'), { recursive: true });
            mkdirSync(join(fixture, REL_SRC), { recursive: true });
            copyFileSync(SCRIPT, join(fixture, 'scripts', 'build-resolvers.mjs'));
            writeFileSync(join(fixture, REL_SRC, 'a.js'), 'export const a = 1;\n');

            const result = runNode(join(fixture, 'scripts', 'build-resolvers.mjs'), fixture);
            expect(result.status).not.toBe(0);
            expect(result.stderr).toContain('npm ci');
            expect(result.stderr).not.toContain("Cannot find package 'esbuild'");
        } finally {
            rmSync(fixture, { recursive: true, force: true });
        }
    });
});
