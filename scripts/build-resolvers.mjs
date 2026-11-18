import { mkdir, readdir, rm, writeFile } from 'node:fs/promises';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const srcDir = join(import.meta.dirname, '..', 'tofu', 'application', 'appsync', 'js-resolvers');
const outDir = join(import.meta.dirname, '..', 'tofu', 'application', 'appsync', 'dist');

/**
 * The esbuild options every APPSYNC_JS artifact is built with, and what a bundle is
 * re-rendered with once it is too big for AppSync. All three are exported so
 * `tests/unit/check_appsync_code_size.test.ts` measures the bytes the deploy submits
 * instead of a copy of these flags that could drift — the drift would hide the next
 * breach, and this class of breach only ever shows up in a deploy.
 *
 * AppSync refuses a function or resolver whose `code` is outside the range 1 - 32768
 * characters, and it validates that at `CreateFunction`/`UpdateFunction`/
 * `CreateResolver` time: the Node resolver tests run against the `js-resolvers` sources,
 * the guards check those sources, and `tofu plan` sees the length only in the deploy's
 * pre-flight plan. Dev deploy run 44236797227 (the squash merge of PR #956) died exactly
 * that way, with `create_order_fn` at 33061 characters — 293 over — once the custody-sale
 * work and its `lib/` imports were inlined into that one function.
 */
export const bundleOptions = {
    bundle: true,
    platform: 'neutral',
    target: 'es2020',
    format: 'esm',
    external: ['@aws-appsync/utils'],
};

/**
 * Whitespace and comment stripping only: identifiers and syntax are untouched, so the code
 * AppSync runs stays readable in the console and the constructs
 * `check_appsync_js_compatibility.test.ts` bans stay visible in their authored shape. It
 * takes `create_order_fn` from 33061 to 26179 characters. Full `--minify` would reach
 * 17152, but it renames identifiers and rewrites syntax, so it stays a reserve lever.
 */
export const minifiedBundleOptions = { ...bundleOptions, minifyWhitespace: true };

/**
 * Re-render a bundle in `minifiedBundleOptions` once its plain render exceeds this many
 * characters — 75% of AppSync's 32768-character limit, so a function reaches the hard
 * limit only by growing past a threshold that no current artifact is near except the one
 * that already broke the deploy.
 *
 * The threshold exists so the fix does not touch the whole API. AppSync updates are driven
 * by the code string, so minifying every bundle would change every entry in
 * `resolver_code_hashes.tf`: all 173 functions rewritten, and every pipeline resolver that
 * carries `replace_triggered_by` on its own code hash replaced outright — a replaced
 * resolver has no resolver for its field for the length of the apply. Measured against the
 * plain build, this rule changes exactly one artifact's bytes. The number is a fixed
 * constant rather than a per-build decision, so an artifact cannot oscillate between the
 * two shapes across deploys.
 */
export const CODE_MINIFY_TRIGGER = 24576;

/**
 * One artifact, rendered exactly as `dist/` will hold it, so the guard and the build cannot
 * disagree about what AppSync is being asked to accept.
 */
export async function renderArtifact(esbuild, entryPoint) {
    const plain = await esbuild.build({ ...bundleOptions, entryPoints: [entryPoint], write: false });
    const code = plain.outputFiles[0].text;
    if (code.length <= CODE_MINIFY_TRIGGER) {
        return { code, minified: false };
    }
    const stripped = await esbuild.build({ ...minifiedBundleOptions, entryPoints: [entryPoint], write: false });
    return { code: stripped.outputFiles[0].text, minified: true };
}

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

    // Same loud-failure rule one level in: an empty entry list would otherwise
    // replace dist/ with nothing, and every `file()` call in the module fails.
    if (entryPoints.length === 0) {
        console.error(`No .js entry points found in ${srcDir}; refusing to replace dist/.`);
        process.exit(1);
    }

    await rm(outDir, { recursive: true, force: true });
    await mkdir(outDir, { recursive: true });

    const stripped = [];
    for (const entryPoint of entryPoints) {
        const { code, minified } = await renderArtifact(esbuild, entryPoint);
        if (minified) {
            stripped.push(basename(entryPoint));
        }
        await writeFile(join(outDir, basename(entryPoint)), code);
    }

    if (stripped.length > 0) {
        console.log(
            `Resolvers bundled successfully (whitespace and comments stripped above ` +
                `${CODE_MINIFY_TRIGGER} characters: ${stripped.join(', ')})`
        );
        return;
    }
    console.log('Resolvers bundled successfully');
}

// Run only when this file is the program. The size guard imports the bundle options and
// `renderArtifact` from here, and importing must not rebuild the repo's `dist/` under it.
const invokedAsProgram = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedAsProgram) {
    build().catch(err => {
        console.error(err);
        process.exit(1);
    });
}
