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
 * AppSync refuses a function or resolver whose `code` is outside the range 1 - 32768, and
 * it validates that at `CreateFunction`/`UpdateFunction`/`CreateResolver` time: the Node
 * resolver tests run against the `js-resolvers` sources, the guards check those sources,
 * and `tofu plan` sees the length only in the deploy's pre-flight plan. Dev deploy run
 * 44236797227 (the squash merge of PR #956) died exactly that way, with `create_order_fn`
 * at 33061 — 293 over — once the custody-sale work and its `lib/` imports were inlined
 * into that one function.
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
 * takes `create_order_fn` from 33061 bytes to 26179. Full `--minify` would reach 17152,
 * but it renames identifiers and rewrites syntax, so it stays a reserve lever.
 */
export const minifiedBundleOptions = { ...bundleOptions, minifyWhitespace: true };

/**
 * The range AppSync accepts for one function or resolver `code` string, counted in bytes:
 * the AWS provider validates the attribute with `validation.StringLenBetween(1, 32768)`, so
 * 1 is the lower bound the empty bundle test asserts and this is the upper one.
 */
export const APPSYNC_CODE_MAX = 32768;

/**
 * Re-render a bundle in `minifiedBundleOptions` once its plain render exceeds this many
 * bytes — 75% of AppSync's limit, so a function reaches the hard limit only by growing past
 * a threshold that no current artifact is near except the one that already broke the deploy.
 *
 * The threshold exists so the fix does not touch the whole API. AppSync updates are driven
 * by the code string, so minifying every bundle would change every entry in
 * `resolver_code_hashes.tf`: all 173 functions rewritten, and every pipeline resolver that
 * carries `replace_triggered_by` on its own code hash replaced outright — a replaced
 * resolver has no resolver for its field for the length of the apply. Measured against the
 * plain build, this rule changes exactly one artifact's bytes. The number is a fixed
 * constant rather than a per-build decision, so an artifact cannot oscillate between the
 * two shapes across deploys.
 *
 * The decision is made on the template's own bytes, because that is what this function
 * renders. `check_appsync_code_size.test.ts` enforces the limit on the bytes AppSync is
 * actually handed — after `templatefile()` substitution — so the trigger leaving room at
 * 75% is what keeps a substituted artifact clear of the hard limit.
 */
export const CODE_MINIFY_TRIGGER = Math.floor(APPSYNC_CODE_MAX * 0.75);

/**
 * The unit every size decision here uses: UTF-8 bytes.
 *
 * `aws_appsync_function.code` is validated by the AWS provider's
 * `validation.StringLenBetween(1, 32768)`, and that helper calls Go's `len(string)` — a byte
 * count. JavaScript's `code.length` counts UTF-16 code units, so a bundle carrying multi-byte
 * text reads *smaller* to JS than to the provider: the artifact passes every PR check and is
 * then rejected at `CreateFunction`. Counting characters is the mistake this exists to
 * prevent — a guard that measures 32000 characters certifies a 40000-byte artifact. The
 * difference is reachable through this toolchain, not theoretical: esbuild escapes non-ASCII
 * in string literals and identifiers to ASCII (`é` becomes `\xE9`), but it copies `/*!`-style
 * legal comments through verbatim, and so does `minifyWhitespace`. The build's threshold and
 * `check_appsync_code_size.test.ts`'s limit both go through this function, so the two cannot
 * measure different boundaries.
 */
export function codeByteLength(code) {
    return Buffer.byteLength(code, 'utf8');
}

/**
 * The documented maximum length of a DynamoDB table name: AWS allows 3-255 characters of
 * `[a-zA-Z0-9._-]`. Every `templatefile()` placeholder in the AppSync module maps to
 * `var.dynamodb_table_names.<key>`, which the guard checks, so 255 bytes is a documented
 * ceiling on what tofu can substitute for one — an upper bound, not an estimate. The real
 * dev/prod/ephemeral names are around 30 characters, so the guard stays conservative
 * without modelling each environment's `name_prefix` and `table_suffix`, and it cannot
 * under-count a future environment.
 */
export const MAX_TABLE_NAME_BYTES = 255;

/**
 * A `templatefile()` interpolation. `$${` is Terraform's escape for a literal `${`, so a
 * sequence preceded by `$` is skipped, exactly as
 * `tests/unit/check_templatefile_escaping.test.ts` reads it.
 */
const TEMPLATE_INTERPOLATION = /(?<!\$)\$\{([^}]*)\}/g;

/**
 * The size of one rendered artifact as AppSync will see it.
 *
 * A `templatefile()` artifact is measured with every placeholder the call site declares
 * replaced by the widest value that placeholder can take, because that is the string tofu
 * submits. A `file()` artifact gets no substitution at all: a `${...}` there is a
 * JavaScript template literal and reaches AppSync literally, so charging an allowance for
 * it would inflate the measurement and hide nothing.
 *
 * A placeholder present in the bundle but not declared by the call site is returned in
 * `undeclared` rather than silently left unsubstituted: tofu fails `plan` on that, and a
 * size bound that quietly treated it as literal text would be unsound as well as wrong.
 */
export function measureArtifactBytes(code, { kind = 'file', placeholders = [] } = {}) {
    const templateBytes = codeByteLength(code);
    if (kind !== 'templatefile') {
        return { bytes: templateBytes, templateBytes, undeclared: [] };
    }
    const declared = new Set(placeholders);
    const undeclared = new Set();
    const expanded = code.replace(TEMPLATE_INTERPOLATION, (whole, rawName) => {
        const name = String(rawName).trim();
        if (!declared.has(name)) {
            undeclared.add(whole);
            return whole;
        }
        return 'x'.repeat(MAX_TABLE_NAME_BYTES);
    });
    return { bytes: codeByteLength(expanded), templateBytes, undeclared: [...undeclared] };
}

/**
 * One artifact, rendered exactly as `dist/` will hold it, so the guard and the build cannot
 * disagree about what AppSync is being asked to accept.
 */
export async function renderArtifact(esbuild, entryPoint) {
    const plain = await esbuild.build({ ...bundleOptions, entryPoints: [entryPoint], write: false });
    const code = plain.outputFiles[0].text;
    if (codeByteLength(code) <= CODE_MINIFY_TRIGGER) {
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
                `${CODE_MINIFY_TRIGGER} bytes: ${stripped.join(', ')})`
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
