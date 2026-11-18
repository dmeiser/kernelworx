import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';
import { CODE_MINIFY_TRIGGER, renderArtifact } from '../../scripts/build-resolvers.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');
const APPSYNC_MODULE_DIR = join(ROOT_DIR, 'tofu', 'application', 'modules', 'appsync');

/**
 * AppSync refuses a function or resolver whose `code` is not in the range 1 - 32768
 * characters, and it validates that at `CreateFunction`/`UpdateFunction`/`CreateResolver`
 * time. Nothing before a deploy sees the length: the Node resolver tests run against the
 * `js-resolvers` sources, the other guards parse those sources too, and `tofu plan` reports
 * it only in the deploy's pre-flight plan. Dev deploy run 44236797227 — the squash merge of
 * PR #956 — lost the whole dev deploy this way: `create_order_fn` reached 33061 characters
 * once the custody-sale work and its `lib/` imports were inlined into that one function, and
 * all seven PR checks were green.
 *
 * So this guard measures the bundle, not the sources, and measures it through the build
 * script's own `renderArtifact` (`CODE_MINIFY_TRIGGER` and both option sets live there): a
 * copy of the flags here could drift, and a drifted copy is exactly what would hide the next
 * breach. It renders in memory rather than reading `dist/`, which is generated and may be
 * stale or mid-rebuild under the parallel guard files.
 */
const APPSYNC_CODE_MAX = 32768;

/**
 * A `templatefile()` call substitutes every `${placeholder}` with an environment value — a
 * DynamoDB table name or an AppSync id — so the rendered `code` is longer than the template
 * tofu reads. Measured expansion is a handful of characters per placeholder
 * (`${order_fulfillments_table_name}` is 32 characters in the template, 37 rendered), and
 * this budget is shared by every placeholder in one artifact, so the guard cannot
 * underestimate it.
 */
const PLACEHOLDER_EXPANSION_ALLOWANCE = 64;

/** Every `.tf` file in the AppSync module, sorted, so failures are reproducible. */
function moduleTerraformFiles(dir: string): string[] {
    return readdirSync(dir)
        .filter((f) => f.endsWith('.tf'))
        .map((f) => join(dir, f))
        .filter((f) => statSync(f).isFile())
        .sort();
}

/** Drop HCL comment lines, so comment prose about `file()` is not counted. */
function stripHclComments(content: string): string {
    return content
        .split('\n')
        .filter((line) => !/^\s*(#|\/\/)/.test(line))
        .join('\n');
}

/**
 * The source directory behind `${local.js_resolvers_dir}`. `variables.tf` points at the
 * generated `appsync/dist`, and the build bundles the `js-resolvers` sibling of that
 * directory, so names resolve against the sources.
 */
function resolverSourceDir(): string {
    const variables = readFileSync(join(APPSYNC_MODULE_DIR, 'variables.tf'), 'utf8');
    const match = variables.match(/^\s*js_resolvers_dir\s*=\s*"\$\{path\.module\}\/(\S*?)"\s*$/m);
    if (!match) {
        throw new Error('could not find local.js_resolvers_dir in modules/appsync/variables.tf');
    }
    const bundledDir = join(APPSYNC_MODULE_DIR, match[1]);
    expect(bundledDir.endsWith(join('appsync', 'dist'))).toBe(true);
    return join(dirname(bundledDir), 'js-resolvers');
}

const SOURCE_DIR = resolverSourceDir();

const CODE_SOURCE = /(?:templatefile|file)\(\s*"\$\{local\.js_resolvers_dir\}\/([^"]+?)"/g;

/**
 * Code artifacts the module submits to AppSync, derived from the Terraform so a new function
 * or resolver is covered automatically. Only `code =` call sites: the `filesha256()` inputs
 * in `resolver_code_hashes.tf` name the same files and are not code.
 */
function codeArtifacts(): { name: string; tfFile: string }[] {
    const artifacts: { name: string; tfFile: string }[] = [];
    for (const tfFile of moduleTerraformFiles(APPSYNC_MODULE_DIR)) {
        const content = stripHclComments(readFileSync(tfFile, 'utf8'));
        const codeCallSites = [...content.matchAll(/code\s*=\s*(?:templatefile|file)\(/g)].length;
        const namedCallSites = [...content.matchAll(CODE_SOURCE)];
        expect(namedCallSites.length, `${tfFile} has a code call site this guard cannot name`).toBe(codeCallSites);
        for (const match of namedCallSites) {
            const name = match[1];
            expect(name.endsWith('.js'), `${tfFile} has a non-literal resolver filename`).toBe(true);
            expect(() => statSync(join(SOURCE_DIR, name)), `${tfFile} names a missing ${name}`).not.toThrow();
            artifacts.push({ name, tfFile: tfFile.replace(`${ROOT_DIR}/`, '') });
        }
    }
    return artifacts;
}

/** One artifact as deployed: rendered code plus the placeholder budget on top. */
async function measure(name: string): Promise<{ rendered: number; budget: number; minified: boolean }> {
    const { code, minified } = await renderArtifact(esbuild, join(SOURCE_DIR, name));
    const placeholders = (code.match(/\$\{[A-Za-z0-9_]+\}/g) ?? []).length;
    const rendered = code.length - placeholders * '${placeholder}'.length;
    return { rendered, budget: rendered + placeholders * PLACEHOLDER_EXPANSION_ALLOWANCE, minified };
}

describe('AppSync 32768-character code limit (deploy run 44236797227)', () => {
    it(
        'renders every function and resolver body inside the range AppSync accepts',
        async () => {
            const artifacts = codeArtifacts();
            // A guard that quietly measures nothing is the failure mode that lost this
            // deploy: the compatibility guard once walked one directory and three patterns.
            expect(artifacts.length, 'AppSync code call sites in the module').toBeGreaterThanOrEqual(40);

            const measured: { name: string; rendered: number; budget: number; minified: boolean }[] = [];
            const breaches: string[] = [];
            for (const artifact of artifacts) {
                const size = await measure(artifact.name);
                measured.push({ name: artifact.name, ...size });
                if (size.budget > APPSYNC_CODE_MAX) {
                    breaches.push(
                        `${artifact.name}: ~${size.rendered} characters rendered ` +
                            `(${size.minified ? 'stripped' : 'not stripped'} at build time, budget ${size.budget} of ` +
                            `${APPSYNC_CODE_MAX}), named by ${artifact.tfFile}`,
                    );
                }
            }

            measured.sort((a, b) => b.budget - a.budget);
            expect(
                breaches,
                `AppSync refuses code outside 1 - ${APPSYNC_CODE_MAX} characters at CreateFunction time, so a breach ` +
                    'fails a deploy and no PR check. Largest artifacts this branch renders:\n' +
                    measured
                        .slice(0, 5)
                        .map((m) => `  ${m.name}: ${m.rendered} chars, budget ${m.budget}${m.minified ? ' (stripped)' : ''}`)
                        .join('\n') +
                    `\nStripping starts above ${CODE_MINIFY_TRIGGER} characters, so the ceiling here is that number plus ` +
                    'whatever a stripped bundle still costs. Move the step work into a pipeline function that still has ' +
                    'room, or split it across the steps that do — a resolver hard-caps at 10 functions and a JS function ' +
                    'gets exactly one datastore call, so the cap that bounds the steps bounds the fix too.',
            ).toEqual([]);
        },
        120000,
    );

    it('keeps every rendered body non-empty (the lower bound of the same range)', async () => {
        for (const artifact of codeArtifacts()) {
            const size = await measure(artifact.name);
            expect(size.rendered, `${artifact.name} renders an empty body`).toBeGreaterThan(0);
        }
    }, 120000);
});
