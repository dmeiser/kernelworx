/**
 * Regression tests for the complexity-disable ratchet (issue #532).
 *
 * Runs in the default jsdom environment (tests/setup.ts is jsdom-only), which is
 * fine: the Node `child_process`/`fs` APIs used below work in either environment.
 *
 * `frontend/eslint.config.js` sets `complexity: ['error', { max: 5 }]`, but the
 * rule is switched off by `eslint-disable` directives for specific functions.
 * `scripts/check-complexity-disables.mjs` enforces that the total count can
 * only shrink against the committed `scripts/complexity-disables.baseline` —
 * these tests pin that gate's contract so it cannot silently rot.
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(join(here, '..'))
const scriptPath = join(frontendRoot, 'scripts', 'check-complexity-disables.mjs')
const baselinePath = join(frontendRoot, 'scripts', 'complexity-disables.baseline')

// Temp fixtures live under the frontend root, not the OS temp dir: the global
// test environment is jsdom, which intercepts `node:os` tmpdir() and would
// redirect it into the project tree with a non-POSIX path.
const tempRoot = join(frontendRoot, 'node_modules', '.tmp-complexity-disables')
mkdirSync(tempRoot, { recursive: true })
const tempDirs: string[] = []
function run(args: string[]): { status: number; stdout: string; stderr: string } {
  try {
    const stdout = execFileSync(process.execPath, [scriptPath, ...args], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    return { status: 0, stdout, stderr: '' }
  } catch (err) {
    const e = err as { status?: number; stdout?: string; stderr?: string }
    return {
      status: e.status ?? 1,
      stdout: e.stdout ?? '',
      stderr: e.stderr ?? '',
    }
  }
}

function makeFixtures(disableLines: string[]): string {
  const dir = mkdtempSync(join(tempRoot, 'run-'))
  tempDirs.push(dir)
  const srcDir = join(dir, 'src')
  mkdirSync(join(srcDir, 'pages'), { recursive: true })
  const fn = (name: string, body: string) =>
    `export function ${name}() {\n${body}\n}\n`
  writeFileSync(join(srcDir, 'a.ts'), fn('a', disableLines[0] ?? ''))
  writeFileSync(
    join(srcDir, 'pages', 'b.tsx'),
    fn('b', [disableLines[1], disableLines[2]].filter(Boolean).join('\n')),
  )
  return dir
}

afterAll(() => {
  for (const dir of tempDirs) rmSync(dir, { recursive: true, force: true })
})

describe('complexity-disable ratchet (issue #532)', () => {
  it('the committed baseline exists, is a plain integer, and matches the tree', () => {
    const baseline = Number.parseInt(readFileSync(baselinePath, 'utf8').trim(), 10)
    expect(Number.isInteger(baseline)).toBe(true)
    const res = run([])
    expect(res.status).toBe(0)
    expect(res.stdout).toContain(`ok: ${baseline} complexity-disable directives`)
  })

  it('fails when the directive count exceeds the baseline (new disable added)', () => {
    const dir = makeFixtures([
      '  // eslint-disable-next-line complexity -- new offender',
      '  // eslint-disable-next-line complexity -- another one',
    ])
    const baseline = join(dir, 'baseline')
    writeFileSync(baseline, '1\n')
    const res = run(['--src-dir', join(dir, 'src'), '--baseline', baseline])
    expect(res.status).toBe(1)
    expect(res.stderr).toContain('error: 2 complexity-disable directives found, baseline is 1')
  })

  it('passes when the directive count is below the baseline', () => {
    const dir = makeFixtures(['  // eslint-disable-next-line complexity'])
    const baseline = join(dir, 'baseline')
    writeFileSync(baseline, '5\n')
    const res = run(['--src-dir', join(dir, 'src'), '--baseline', baseline])
    expect(res.status).toBe(0)
    expect(res.stdout).toContain('ok: 1 complexity-disable directives (baseline 5)')
  })

  it('counts all three directive spellings (block, next-line, line)', () => {
    const dir = makeFixtures([
      '/* eslint-disable complexity */',
      '  // eslint-disable-next-line complexity',
      '  // eslint-disable-line complexity',
    ])
    const baseline = join(dir, 'baseline')
    writeFileSync(baseline, '4\n')
    const res = run(['--src-dir', join(dir, 'src'), '--baseline', baseline])
    expect(res.status).toBe(0)
    expect(res.stdout).toContain('ok: 3 complexity-disable directives')
  })

  it('does not count disables for other rules or non-disable mentions', () => {
    const dir = makeFixtures([
      '  // eslint-disable-next-line no-console',
      '  // complexity is fine here (no directive)',
    ])
    const baseline = join(dir, 'baseline')
    writeFileSync(baseline, '2\n')
    const res = run(['--src-dir', join(dir, 'src'), '--baseline', baseline])
    expect(res.status).toBe(0)
    expect(res.stdout).toContain('ok: 0 complexity-disable directives')
  })

  it('refuses to raise the baseline via --update (raises are deliberate edits)', () => {
    const dir = makeFixtures([
      '  // eslint-disable-next-line complexity',
      '  // eslint-disable-next-line complexity',
    ])
    const baseline = join(dir, 'baseline')
    writeFileSync(baseline, '1\n')
    const res = run(['--src-dir', join(dir, 'src'), '--baseline', baseline, '--update'])
    expect(res.status).toBe(1)
    expect(res.stderr).toContain('refusing to raise the baseline')
    expect(Number.parseInt(readFileSync(baseline, 'utf8').trim(), 10)).toBe(1)
  })

  it('ratchets the baseline down to the current count via --update', () => {
    const dir = makeFixtures(['  // eslint-disable-next-line complexity'])
    const baseline = join(dir, 'baseline')
    writeFileSync(baseline, '7\n')
    const res = run(['--src-dir', join(dir, 'src'), '--baseline', baseline, '--update'])
    expect(res.status).toBe(0)
    expect(res.stdout).toContain('ratcheted baseline down: 7 -> 1')
    expect(Number.parseInt(readFileSync(baseline, 'utf8').trim(), 10)).toBe(1)
  })
})
