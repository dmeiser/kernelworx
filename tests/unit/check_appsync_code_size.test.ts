import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import * as esbuild from 'esbuild';
import {
    APPSYNC_CODE_MAX,
    CODE_MINIFY_TRIGGER,
    MAX_TABLE_NAME_BYTES,
    codeByteLength,
    measureArtifactBytes,
    renderArtifact,
} from '../../scripts/build-resolvers.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');
const APPSYNC_MODULE_DIR = join(ROOT_DIR, 'tofu', 'application', 'modules', 'appsync');

/**
 * AppSync refuses a function or resolver whose `code` is not in the range 1 - 32768, and it
 * validates that at `CreateFunction`/`UpdateFunction`/`CreateResolver` time. Nothing before
 * a deploy sees the length: the Node resolver tests run against the `js-resolvers` sources,
 * the other guards parse those sources too, and `tofu plan` reports it only in the deploy's
 * pre-flight plan. Dev deploy run 44236797227 — the squash merge of PR #956 — lost the whole
 * dev deploy this way: `create_order_fn` reached 33061 bytes once the custody-sale work and
 * its `lib/` imports were inlined into that one function, and all seven PR checks were green.
 *
 * Two boundaries have to be measured, and both are the provider's, not JavaScript's:
 *
 * - The unit is UTF-8 bytes. The AWS provider validates `code` with
 *   `validation.StringLenBetween(1, 32768)`, whose implementation is Go's `len(string)`.
 *   `String.prototype.length` counts UTF-16 code units, so a bundle carrying multi-byte text
 *   reads smaller here than the provider sees it. esbuild escapes non-ASCII in string
 *   literals and identifiers to ASCII, but it preserves `/*!`-style legal comments verbatim,
 *   so the difference is reachable, not hypothetical.
 * - The length is the substituted one. `templatefile()` replaces each declared placeholder
 *   with a real table name before `code` reaches AppSync, so a `file()` artifact is measured
 *   as rendered and a `templatefile()` artifact is measured with each placeholder at the
 *   widest value it can take (`MAX_TABLE_NAME_BYTES`, the documented DynamoDB maximum).
 *
 * Everything here measures through the build script's own exports: a copy of its flags, its
 * threshold or its unit could drift, and a drifted copy is exactly what would hide the next
 * breach. Artifacts are rendered in memory rather than read from `dist/`, which is generated
 * and may be stale or mid-rebuild under the parallel guard files.
 */

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

/**
 * A `code` attribute that loads a JS bundle, with the `templatefile()` vars map captured when
 * the kind is `templatefile`. The vars values in this module are single-line and brace-free, so
 * the non-greedy body match stops at the map's own `}`; anything that shape does not understand
 * has to fail the count check below rather than be skipped.
 */
const CODE_CALL =
    /code\s*=\s*(templatefile|file)\(\s*"\$\{local\.js_resolvers_dir\}\/([^"]+)"(?:\s*,\s*\{([\s\S]*?)\})?\s*\)/g;

/** Placeholder declarations inside a `templatefile()` vars map: `name = <expression>`. */
const VAR_ENTRY = /(^|\n)\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\n]*)/g;

interface CodeArtifact {
    name: string;
    tfFile: string;
    kind: 'file' | 'templatefile';
    placeholders: string[];
}

/**
 * Code artifacts the module submits to AppSync, derived from the Terraform so a new function
 * or resolver is covered automatically, each carrying the kind and placeholder names that
 * decide how it has to be measured.
 */
function codeArtifacts(): CodeArtifact[] {
    const artifacts: CodeArtifact[] = [];
    for (const tfFile of moduleTerraformFiles(APPSYNC_MODULE_DIR)) {
        const content = stripHclComments(readFileSync(tfFile, 'utf8'));
        const relFile = tfFile.slice(ROOT_DIR.length + 1);

        // Every `code` attribute in the module, in any assignment form. A `code = local.x` or
        // `code = jsonencode(...)` would be invisible to the named pattern below, so the two
        // counts are pinned equal and the convention fails loudly instead of bypassing this
        // guard silently.
        const assignments = [...content.matchAll(/(^|\n)\s*code\s*=/g)].length;
        const namedCallSites = [...content.matchAll(CODE_CALL)];
        expect(namedCallSites.length, `${relFile} has a code assignment this guard cannot name`).toBe(assignments);

        for (const match of namedCallSites) {
            const [, kind, name, varsBody] = match;
            expect(name.endsWith('.js'), `${relFile} has a non-literal resolver filename`).toBe(true);
            expect(() => statSync(join(SOURCE_DIR, name)), `${relFile} names a missing ${name}`).not.toThrow();

            const placeholders: string[] = [];
            if (kind === 'templatefile') {
                expect(varsBody, `${relFile} has a templatefile() call with no vars map this guard can read`).toBeTruthy();
                const entries = [...(varsBody as string).matchAll(VAR_ENTRY)];
                expect(entries.length, `${relFile} declares no placeholders for ${name}`).toBeGreaterThan(0);
                for (const entry of entries) {
                    const [, , placeholder, rawValue] = entry;
                    const value = rawValue.trim().replace(/,+\s*$/, '');
                    // The 255-byte ceiling this guard charges each placeholder is DynamoDB's
                    // documented table-name maximum, so it only bounds a substitution whose value
                    // is in fact a table name. Anything else needs its own documented bound.
                    expect(
                        /^var\.dynamodb_table_names\.[a-z0-9_]+$/.test(value),
                        `${relFile} binds \${${placeholder}} to ${value || '<nothing>'}; the size guard can only bound a ` +
                            'templatefile() placeholder whose value is var.dynamodb_table_names.<key>',
                    ).toBe(true);
                    placeholders.push(placeholder);
                }
            } else {
                expect(varsBody, `${relFile} has a file() call site with an unexpected trailing body`).toBeFalsy();
            }
            artifacts.push({ name, tfFile: relFile, kind, placeholders });
        }
    }
    return artifacts;
}

/** One artifact as deployed: the bytes AppSync is handed, plus the template's own bytes. */
function measureArtifact(artifact: CodeArtifact, code: string) {
    return measureArtifactBytes(code, { kind: artifact.kind, placeholders: artifact.placeholders });
}

async function render(name: string): Promise<{ code: string; minified: boolean }> {
    return renderArtifact(esbuild, join(SOURCE_DIR, name));
}

describe('AppSync 32768-byte code limit (deploy run 44236797227)', () => {
    it(
        'renders every function and resolver body inside the range AppSync accepts',
        async () => {
            const artifacts = codeArtifacts();
            // A guard that quietly measures nothing is the failure mode that lost this
            // deploy: the compatibility guard once walked one directory and three patterns.
            expect(artifacts.length, 'AppSync code call sites in the module').toBeGreaterThanOrEqual(200);

            const measured: { name: string; kind: string; bytes: number; templateBytes: number; minified: boolean }[] = [];
            const breaches: string[] = [];
            for (const artifact of artifacts) {
                const { code, minified } = await render(artifact.name);
                const size = measureArtifact(artifact, code);
                measured.push({ name: artifact.name, kind: artifact.kind, ...size, minified });
                if (size.undeclared.length > 0) {
                    breaches.push(
                        `${artifact.name}: ${artifact.tfFile} renders ${size.undeclared.join(', ')} but does not declare ` +
                            'it, so tofu would fail plan and no substitution bound can be trusted for it',
                    );
                }
                if (size.bytes > APPSYNC_CODE_MAX) {
                    breaches.push(
                        `${artifact.name}: ${size.bytes} bytes as deployed (${size.templateBytes} as rendered, ` +
                            `${artifact.kind}, ${size.undeclared.length} undeclared placeholder(s), ` +
                            `${minified ? 'stripped' : 'not stripped'} at build time), named by ${artifact.tfFile}`,
                    );
                }
                expect(size.bytes, `${artifact.name} renders an empty body`).toBeGreaterThan(0);
            }

            measured.sort((a, b) => b.bytes - a.bytes);
            expect(
                breaches,
                `AppSync refuses code outside 1 - ${APPSYNC_CODE_MAX} bytes at CreateFunction time, so a breach fails a ` +
                    'deploy and no PR check. Largest artifacts this branch renders:\n' +
                    measured
                        .slice(0, 5)
                        .map((m) => `  ${m.name}: ${m.bytes} bytes as deployed, ${m.templateBytes} as rendered (${m.kind})`)
                        .join('\n') +
                    `\nThe build strips whitespace and comments above ${CODE_MINIFY_TRIGGER} rendered bytes, so the room ` +
                    'left for templatefile() substitution is the difference. Move the step work into a pipeline function ' +
                    'that still has room, or split it across the steps that do — a resolver hard-caps at 10 functions and ' +
                    'a JS function gets exactly one datastore call, so the cap that bounds the steps bounds the fix too.',
            ).toEqual([]);
        },
        180000,
    );

    it('holds every templatefile() placeholder to the documented DynamoDB name bound', () => {
        // The bound is only sound while every placeholder is a table name, which the parser
        // above asserts; this pins the assertion to the documented maximum itself.
        expect(MAX_TABLE_NAME_BYTES, 'DynamoDB table names are documented at 3-255 characters').toBe(255);
    });
});

describe('the size boundary is the provider boundary, not JavaScript’s', () => {
    it('counts UTF-8 bytes rather than UTF-16 code units', () => {
        // The difference the provider acts on: one character, two bytes, and an astral
        // character is one JS code pair but four bytes.
        expect(codeByteLength('é')).toBe(2);
        expect(codeByteLength('😀')).toBe(4);
        expect(codeByteLength('aé€')).toBe(1 + 2 + 3);
        expect(codeByteLength('é'.repeat(1000))).toBe(2000);
        expect(codeByteLength('é'.repeat(1000))).toBeGreaterThan('é'.repeat(1000).length);
    });

    it('strips a bundle whose bytes cross the trigger while its characters do not', async () => {
        // esbuild escapes non-ASCII in string literals and identifiers to ASCII, but it keeps
        // `/*! ... */` legal comments verbatim, so multi-byte text does reach the deployed
        // bytes. This fixture is 12288 characters of é in a legal comment: the plain render is
        // just over the trigger in bytes and well under it in characters, so a character count
        // would have deployed it unstripped.
        const scratch = join(tmpdir(), `appsync-code-size-${process.pid}-${Date.now()}`);
        mkdirSync(scratch, { recursive: true });
        try {
            const entry = join(scratch, 'multi_byte_fn.js');
            writeFileSync(entry, `/*! ${'é'.repeat(CODE_MINIFY_TRIGGER / 2)} */\nexport const handler = () => ({});\n`);

            const plain = await esbuild.build({
                bundle: true,
                platform: 'neutral',
                target: 'es2020',
                format: 'esm',
                external: ['@aws-appsync/utils'],
                entryPoints: [entry],
                write: false,
            });
            const plainCode = plain.outputFiles[0].text;
            expect(plainCode).toContain('é');
            expect(plainCode.length).toBeLessThan(CODE_MINIFY_TRIGGER);
            expect(codeByteLength(plainCode)).toBeGreaterThan(CODE_MINIFY_TRIGGER);

            const built = await renderArtifact(esbuild, entry);
            expect(built.minified, 'a byte-sized artifact under the character count must still be stripped').toBe(true);
            expect(codeByteLength(built.code)).toBeLessThan(codeByteLength(plainCode));
        } finally {
            rmSync(scratch, { recursive: true, force: true });
        }
    });
});

describe('templatefile() substitution is measured, not estimated', () => {
    it('charges every declared placeholder the documented maximum', () => {
        const placeholders = ['orders_table_name', 'campaigns_table_name', 'table_name'];
        const code = `${'a'.repeat(1000)}${placeholders.map((p) => '${' + p + '}').join('')}`;
        const templateBytes = codeByteLength(code);
        const declaredBytes = placeholders.reduce((sum, p) => sum + codeByteLength('${' + p + '}'), 0);

        const size = measureArtifactBytes(code, { kind: 'templatefile', placeholders });
        expect(size.templateBytes).toBe(templateBytes);
        expect(size.bytes).toBe(templateBytes - declaredBytes + placeholders.length * MAX_TABLE_NAME_BYTES);
        expect(size.undeclared).toEqual([]);
    });

    it('catches an artifact a fixed 64-character allowance would have certified', () => {
        // The regression this replaces: a near-limit bundle carrying placeholders is over the
        // limit once substituted, and an allowance smaller than the substituted value passes
        // it. Ten `${table_name}` placeholders are 13 bytes each in the template and at most
        // 255 bytes substituted.
        const body = 'a'.repeat(APPSYNC_CODE_MAX - 1000);
        const code = `${body}${'${table_name}'.repeat(10)}`;
        const declared = measureArtifactBytes(code, { kind: 'templatefile', placeholders: ['table_name'] });
        const estimate = codeByteLength(code) - 10 * '${placeholder}'.length + 10 * 64;

        expect(declared.bytes).toBeGreaterThan(APPSYNC_CODE_MAX);
        expect(estimate).toBeLessThan(APPSYNC_CODE_MAX);
    });

    it('leaves a JavaScript template literal in a file() artifact unsubstituted', () => {
        // A `file()` artifact is handed to AppSync exactly as rendered, so `${value}` inside a
        // JS template literal costs exactly what it costs — charging a substitution allowance
        // for it inflates the measurement and hides nothing.
        const code = 'export const handler = () => `a${value}b${other}`;';
        const exact = codeByteLength(code);
        expect(measureArtifactBytes(code, { kind: 'file' }).bytes).toBe(exact);
        expect(measureArtifactBytes(code, { kind: 'file', placeholders: ['value'] }).bytes).toBe(exact);
    });

    it('reports an interpolation the call site does not declare', () => {
        // tofu fails plan on this, and a bound that treated it as literal text would also be
        // unsound, so it is surfaced rather than counted quietly.
        const code = 'const t = "${undeclared_table}";';
        const size = measureArtifactBytes(code, { kind: 'templatefile', placeholders: ['table_name'] });
        expect(size.undeclared).toEqual(['${undeclared_table}']);
    });

    it('keeps an escaped $${...} literal at its own length', () => {
        // `$${` is templatefile()'s escape: the artifact gains `${...}` and nothing else.
        const code = 'const t = "$${notATable}";';
        expect(measureArtifactBytes(code, { kind: 'templatefile', placeholders: [] }).bytes).toBe(codeByteLength(code));
    });
});
