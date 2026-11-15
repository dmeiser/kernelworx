import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');
const APPSYNC_MODULE_DIR = join(ROOT_DIR, 'tofu', 'application', 'modules', 'appsync');

/**
 * Constructs the APPSYNC_JS 1.0.0 runtime refuses to load. A resolver or pipeline
 * function that uses one is rejected at `CreateFunction`/`UpdateFunction` with
 * `BadRequestException: The code contains one or more errors.` — the deploy fails,
 * Node unit tests pass, and nothing else in the toolchain notices.
 *
 * Every entry is either named by the supported-features reference
 * (https://docs.aws.amazon.com/appsync/latest/devguide/supported-features.html)
 * or found by a deploy that failed. `String(...)` is the second kind: deploy run
 * 43759285075 rejected exactly the four bundles that called it and accepted the
 * 167 that did not.
 */
interface Banned {
    name: string;
    pattern: RegExp;
    instead: string;
}

const BANNED: Banned[] = [
    {
        name: 'the primitive-conversion globals (String/Number/Boolean/BigInt/Symbol)',
        pattern: /(^|[^A-Za-z0-9_$.])(String|Number|Boolean|BigInt|Symbol)\s*\(/,
        instead: 'a `value + \'\'` concatenation, or a `typeof` check plus the value itself',
    },
    {
        // Only Number.isFinite and Number.isNaN are in the supported set.
        name: 'Number methods outside isFinite/isNaN',
        pattern: /Number\.(?!isFinite\b|isNaN\b)[A-Za-z]/,
        instead: 'Number.isFinite or Number.isNaN',
    },
    {
        name: 'Function.prototype call/apply/bind, and hasOwnProperty',
        pattern: /\.(call|apply|bind|hasOwnProperty)\s*\(|(^|[^A-Za-z0-9_$.])Function\s*\(/,
        instead: 'Object.hasOwn(obj, key) and a direct method call',
    },
    {
        name: 'Array.prototype.sort with a comparator',
        pattern: /\.sort\(\s*[^\s)]/,
        instead: 'a sort of the values as they already compare',
    },
    {
        name: 'a regular expression (RegExp, .match, .search)',
        pattern: /(^|[^A-Za-z0-9_$.])RegExp\s*\(|\.(match|search)\s*\(/,
        instead: 'indexOf/substring/split/startsWith/endsWith, or a Java-style pattern string where one is accepted',
    },
    {
        name: 'the classic for (init; condition; afterthought) loop',
        pattern: /\bfor\s*(?:await\s+)?\([^)]*;[^)]*;/,
        instead: 'for-of, for-in, or an array method',
    },
    {
        name: 'the while or do-while loop',
        pattern: /(^|[^A-Za-z0-9_$.])(while|do)\s*\(/,
        instead: 'for-of, or an explicit bounded sequence of steps',
    },
    {
        name: 'try / catch / finally / throw / continue',
        pattern: /(^|[^A-Za-z0-9_$.])(try|catch|finally|throw|continue)\b/,
        instead: 'util.error(...) and the error fields on ctx.error / ctx.prev.error',
    },
    {
        name: 'the ++ / -- / ~ unary operators',
        pattern: /(\+\+|--(?![>=]))|(?<![!~=<>])~(?!=)/,
        instead: '`x = x + 1`',
    },
    {
        name: 'async, await, a promise, or a constructor',
        pattern: /(^|[^A-Za-z0-9_$.])(async|await|Promise|new\s+[A-Za-z])/,
        instead: 'one datastore call per function, sequenced by the pipeline',
    },
    {
        name: 'the Date global',
        pattern: /(^|[^A-Za-z0-9_$.])Date\b/,
        instead: 'util.time.nowISO8601() or util.dynamodb.epochMilliSecondsToISO8601(...)',
    },
];

/**
 * The `in` operator is unsupported; `for (const key in obj)` is supported, so a
 * line that opens a for-in is the only place the keyword may appear.
 */
const IN_OPERATOR = /[A-Za-z0-9_$)\]]\s+in\s+[A-Za-z0-9_$'"`[(.]/;

/** A `/` can only open a regex literal after one of these. */
const REGEX_CAN_START = /[({[,=:!&|?;]$/;
const REGEX_KEYWORD_BEFORE =
    /(?:^|[^A-Za-z0-9_$])(?:return|typeof|instanceof|case|do|else|in|of|new|void|delete|yield|await)$/;

/**
 * A regular-expression literal on one line of code (comments and strings are
 * already gone). A `/` that follows a value — `total / count` — is division, so
 * only a `/` that opens a position where an expression is expected counts, and
 * its body is scanned with `\` escapes and `[...]` classes honoured. Written as a
 * scanner rather than one pattern because division and a regex literal differ by
 * what came before, not by anything the slash itself looks like.
 */
function regexLiteralOn(line: string): string | null {
    for (let at = 0; at < line.length; at += 1) {
        if (line[at] !== '/') {
            continue;
        }
        const before = line.slice(0, at).trimEnd();
        if (!before || !(REGEX_CAN_START.test(before) || REGEX_KEYWORD_BEFORE.test(before))) {
            continue;
        }
        let scan = at + 1;
        let insideClass = false;
        while (scan < line.length) {
            const char = line[scan];
            if (char === '\\') {
                scan += 2;
                continue;
            }
            if (char === '[') {
                insideClass = true;
            } else if (char === ']') {
                insideClass = false;
            } else if (char === '/' && !insideClass) {
                break;
            }
            scan += 1;
        }
        if (scan > at + 1 && scan < line.length) {
            return line.slice(at, scan + 1);
        }
    }
    return null;
}

/** Every .tf file in the AppSync module, including ones added later. */
function moduleTerraformFiles(dir: string): string[] {
    return readdirSync(dir)
        .filter((f) => f.endsWith('.tf'))
        .map((f) => join(dir, f))
        .filter((f) => statSync(f).isFile())
        .sort();
}

/** Drop HCL comment lines, so comment prose about file() is not counted. */
function stripHclComments(content: string): string {
    return content
        .split('\n')
        .filter((line) => !/^\s*(#|\/\/)/.test(line))
        .join('\n');
}

/**
 * Where the module reads resolver code from. `variables.tf` points at the bundled
 * directory (`appsync/dist`) that `npm run build:resolvers` produces with
 * `bundle: true`, so the guard walks the `js-resolvers` sources that get inlined
 * into each bundle — dist is generated, gitignored, and may be stale.
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

/** How many JS resolver code sources the module's Terraform declares. */
function declaredCodeSourceCount(): number {
    let callSites = 0;
    let hashInputs = 0;
    for (const tfFile of moduleTerraformFiles(APPSYNC_MODULE_DIR)) {
        const content = stripHclComments(readFileSync(tfFile, 'utf8'));
        callSites += content.split('js_resolvers_dir}/').length - 1;
        hashInputs += content.split('filesha256("${local.js_resolvers_dir}/').length - 1;
    }
    return callSites - hashInputs;
}

/**
 * Entry files the module loads as APPSYNC_JS code, derived from the Terraform so
 * a new resolver or function is covered automatically. Both `file()` and
 * `templatefile()` call sites count: what reaches AppSync is the bundle either
 * way.
 */
function resolverEntryFiles(): string[] {
    const entries = new Set<string>();
    for (const tfFile of moduleTerraformFiles(APPSYNC_MODULE_DIR)) {
        for (const match of stripHclComments(readFileSync(tfFile, 'utf8')).matchAll(CODE_SOURCE)) {
            const fileName = match[1];
            expect(fileName.endsWith('.js'), `${tfFile} has a non-literal resolver filename`).toBe(true);
            const sourceFile = join(SOURCE_DIR, fileName);
            expect(() => statSync(sourceFile), `${tfFile} names a missing ${sourceFile}`).not.toThrow();
            entries.add(sourceFile);
        }
    }
    return [...entries].sort();
}

/** Relative `./lib/foo.js` (and `../foo.js`) imports, which esbuild inlines. */
function localImports(file: string): string[] {
    const specifiers = [...readFileSync(file, 'utf8').matchAll(/(?:from|import)\s+['"](\.[^'"]+)['"]/g)].map((m) => m[1]);
    return specifiers.map((spec) => resolve(dirname(file), spec));
}

/** The entry file plus every local module inlined into its bundle. */
function bundledFiles(entry: string): string[] {
    const seen = new Set<string>();
    const queue = [entry];
    while (queue.length > 0) {
        const file = queue.shift() as string;
        if (seen.has(file)) {
            continue;
        }
        seen.add(file);
        queue.push(...localImports(file));
    }
    return [...seen];
}

/**
 * Comments, string bodies and template-literal bodies removed, line for line, so
 * the patterns above read the code AppSync actually parses. Comment prose is free
 * to NAME a forbidden construct — "never use String()" is how this trap gets
 * handed on — and a banned construct inside a string literal is not code.
 * Line numbers are preserved, and multi-line strings keep their newlines.
 */
function stripNonCode(content: string): string[] {
    const lines: string[] = [];
    let current = '';
    let i = 0;
    const n = content.length;
    while (i < n) {
        const char = content[i];
        const next = content[i + 1];
        if (char === '/' && next === '/') {
            while (i < n && content[i] !== '\n') {
                i += 1;
            }
            continue;
        }
        if (char === '/' && next === '*') {
            i += 2;
            while (i < n && !(content[i] === '*' && content[i + 1] === '/')) {
                if (content[i] === '\n') {
                    lines.push(current);
                    current = '';
                }
                i += 1;
            }
            i += 2;
            continue;
        }
        if (char === '"' || char === "'" || char === '`') {
            const quote = char;
            i += 1;
            while (i < n && content[i] !== quote) {
                if (content[i] === '\\') {
                    i += 1;
                }
                if (content[i] === '\n') {
                    lines.push(current);
                    current = '';
                }
                i += 1;
            }
            i += 1;
            continue;
        }
        if (char === '\n') {
            lines.push(current);
            current = '';
            i += 1;
            continue;
        }
        current += char;
        i += 1;
    }
    lines.push(current);
    return lines;
}

function offenders(file: string): string[] {
    const found: string[] = [];
    stripNonCode(readFileSync(file, 'utf8')).forEach((line, index) => {
        const lineText = line.trimEnd();
        if (!lineText) {
            return;
        }
        const where = `${relative(ROOT_DIR, file)}:${index + 1}`;
        for (const banned of BANNED) {
            if (banned.pattern.test(lineText)) {
                found.push(`${where}: ${banned.name} — use ${banned.instead} (found: ${lineText.trim()})`);
            }
        }
        if (IN_OPERATOR.test(lineText) && !/\bfor\s*\(/.test(lineText)) {
            found.push(`${where}: the in operator — use Object.hasOwn(...) (found: ${lineText.trim()})`);
        }
        const literal = regexLiteralOn(lineText);
        if (literal) {
            found.push(
                `${where}: a regular-expression literal ${literal} — the runtime supports no regular expressions; use ` +
                    `indexOf/substring/split/startsWith/endsWith (found: ${lineText.trim()})`,
            );
        }
    });
    return found;
}

describe('the guard itself (#570-class miss)', () => {
    it('sees a regular-expression literal and not a division', () => {
        const flagged = [
            'const match = raw.match(/\\[([^\\]]*)\\]/);',
            'const r = /re/.test(x);',
            'return /x/.source;',
            'if (/^A/.test(v)) {',
            'foo(a, /re/.test(b));',
        ];
        const divisions = [
            'const ratio = total / count;',
            'const q = (1 / 2) + (a) / (b);',
            'const t = s.split(",").length / 2;',
            'return { share: paid / total };',
        ];
        for (const line of flagged) {
            expect(regexLiteralOn(line), line).not.toBeNull();
        }
        for (const line of divisions) {
            expect(regexLiteralOn(line), line).toBeNull();
        }
    });

    it('reports the constructs that took down deploy run 43759285075', () => {
        // The guard is only a fix for the class if it fails on the code that shipped.
        const lines = [
            'return String(guard.activeUnitCampaignId);',
            'const match = String((error && error.message) || "").match(/\\[([^\\]]*)\\]/);',
            'for (let i = 0; i < parts.length; i++) {',
        ];
        const found = lines.flatMap((line) =>
            BANNED.filter((banned) => banned.pattern.test(line)).map((banned) => banned.name),
        );
        for (const expected of [
            'the primitive-conversion globals (String/Number/Boolean/BigInt/Symbol)',
            'a regular expression (RegExp, .match, .search)',
            'the classic for (init; condition; afterthought) loop',
            'the ++ / -- / ~ unary operators',
        ]) {
            expect(found, expected).toContain(expected);
        }
        expect(regexLiteralOn(lines[1])).not.toBeNull();
    });
});

describe('APPSYNC_JS resolver code avoids constructs the runtime rejects', () => {
    const entries = resolverEntryFiles();

    it('captures every JS resolver code source the module declares', () => {
        // Guards against the guard going vacuous: a call site whose HCL shape this
        // parser does not understand must fail here, not be skipped.
        const parsedCallSites = moduleTerraformFiles(APPSYNC_MODULE_DIR).reduce(
            (total, tfFile) => total + (stripHclComments(readFileSync(tfFile, 'utf8')).match(CODE_SOURCE) || []).length,
            0,
        );
        expect(
            parsedCallSites,
            `the module declares ${declaredCodeSourceCount()} JS resolver code sources but this test parsed ${parsedCallSites}`,
        ).toBe(declaredCodeSourceCount());
        expect(entries.length, 'distinct resolver entry files behind those call sites').toBeGreaterThan(0);
    });

    it('scans the lib/ modules esbuild inlines, not just the entry files', () => {
        // The shape of the #570-class miss: an un-scanned lib/order_origin.js took
        // the whole dev deploy down.
        const scanned = new Set(entries.flatMap(bundledFiles));
        const entryOnly = new Set(entries);
        let inlined = 0;
        for (const file of scanned) {
            if (!entryOnly.has(file)) {
                inlined += 1;
            }
        }
        expect(inlined, 'no lib/ module was reached from any entry file — the import walk is broken').toBeGreaterThan(
            0,
        );
    });

    const scanned = new Map<string, string[]>();
    for (const entry of entries) {
        for (const file of bundledFiles(entry)) {
            if (!scanned.has(file)) {
                scanned.set(file, offenders(file));
            }
        }
    }

    for (const [file, found] of [...scanned.entries()].sort()) {
        it(`${relative(ROOT_DIR, file)} loads as APPSYNC_JS`, () => {
            expect(
                found,
                'APPSYNC_JS 1.0.0 refuses this code at CreateFunction/UpdateFunction with ' +
                    '"BadRequestException: The code contains one or more errors." (deploy run 43759285075 lost ' +
                    'the dev deploy this way). See ' +
                    'https://docs.aws.amazon.com/appsync/latest/devguide/supported-features.html',
            ).toEqual([]);
        });
    }
});
