import * as esbuild from 'esbuild';
import { readdir, rm } from 'node:fs/promises';
import { join } from 'node:path';

async function build() {
    const srcDir = 'tofu/application/appsync/js-resolvers';
    const outDir = 'tofu/application/appsync/dist';

    await rm(outDir, { recursive: true, force: true });

    const files = await readdir(srcDir, { withFileTypes: true });
    const entryPoints = files
        .filter(f => f.isFile() && f.name.endsWith('.js') && !f.name.endsWith('.test.js'))
        .map(f => join(srcDir, f.name));

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
