import { readdir, rm } from 'node:fs/promises';
import { join } from 'node:path';

const srcDir = join(import.meta.dirname, '..', 'tofu', 'application', 'appsync', 'js-resolvers');
const outDir = join(import.meta.dirname, '..', 'tofu', 'application', 'appsync', 'dist');

async function loadEsbuild() {
    try {
        return await import('esbuild');
    } catch {
        console.error(
            "Could not load 'esbuild'. Run `npm ci` at the repo root first, then retry."
        );
        process.exit(1);
    }
}

async function build() {
    let esbuild = await loadEsbuild();

    // Read/validate entry points before deleting the previous bundle: a
    // missing or typo'd source dir must not wipe the last good dist/ (#281).
    const files = await readdir(srcDir, { withFileTypes: true });
    const entryPoints = files
        .filter(f => f.isFile() && f.name.endsWith('.js') && !f.name.endsWith('.test.js'))
        .map(f => join(srcDir, f.name));

    await rm(outDir, { recursive: true, force: true });

    await esbuild.build({
        entryPoints,
        outdir: outDir,
        bundle: true,
        platform: 'neutral',
        target: 'es2020',
        format: 'esm',
        external: ['@aws-appsync/utils'],
        write: true,
    });
    console.log('Resolvers bundled successfully');
}

build().catch(err => {
    console.error(err);
    process.exit(1);
});
