#!/usr/bin/env node
/**
 * Ratchet guard for `complexity` eslint-disable directives (issue #532).
 *
 * The frontend configures `complexity: [error, { max: 5 }]` in eslint.config.js,
 * mirroring the backend's xenon Grade-A policy. Every `eslint-disable` (or
 * `eslint-disable-next-line` / `eslint-disable-line`) for the `complexity` rule
 * switches that gate off for one function, so the total count of such
 * directives is a progress metric: it may only shrink, never grow.
 *
 * This script counts the directives under the directories eslint applies the
 * rule to (default: `src/` plus `tests/`, matching the trailing `ts,tsx`
 * file pattern in eslint.config.js; the ratchet's own test file is
 * excluded because its fixture strings are directive-shaped payloads, not
 * disables), compares the count to the committed baseline in
 * `complexity-disables.baseline` (a single integer), and exits non-zero when
 * the count exceeds the baseline. It never fails when the count is below the
 * baseline; run it with `--update` to ratchet the baseline down to the current
 * count after removing directives. `--update` refuses to raise the baseline —
 * raising it means adding new disables and must be a deliberate, reviewed edit.
 *
 * Usage:
 *   node scripts/check-complexity-disables.mjs            # gate (used by `npm run lint`)
 *   node scripts/check-complexity-disables.mjs --update   # ratchet baseline down
 */

import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const scriptArgs = process.argv.slice(2)

if (scriptArgs.includes('--help')) {
  console.log(
    'usage: node scripts/check-complexity-disables.mjs [--update] [--src-dir <dir>] [--baseline <file>]',
  )
  process.exit(0)
}

const update = scriptArgs.includes('--update')

function argValue(flag) {
  const i = scriptArgs.indexOf(flag)
  return i !== -1 ? scriptArgs[i + 1] : undefined
}

const srcDirArg = argValue('--src-dir')
const defaultRoot = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(join(defaultRoot, '..'))
// The eslint config lints the whole frontend tree (`**/*.{ts,tsx}`), so the
// gate-off count must cover every directory the rule actually applies to, not
// only `src/`. The ratchet's own test file loads directive-shaped fixture
// strings as payloads — those are literals, not disables, and are excluded so
// the count stays equal to the directives eslint honors.
const selfTestRelPath = join('tests', 'complexity-disables-ratchet.test.ts')
const scanDirs = srcDirArg
  ? [isAbsolute(srcDirArg) ? srcDirArg : resolve(join(frontendRoot, srcDirArg))]
  : ['src', 'tests'].map((dir) => join(frontendRoot, dir))
const baselinePath = argValue('--baseline')
  ? resolve(argValue('--baseline'))
  : join(here, 'complexity-disables.baseline')

// Matches any eslint disable directive (block, next-line, or line) that names
// the `complexity` rule, regardless of trailing comments.
const COMPLEXITY_DISABLE = /eslint-disable(?:-next-line|-line)?\s+.*\bcomplexity\b/

function collectFiles(dir) {
  const out = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'dist') continue
      out.push(...collectFiles(full))
    } else if (entry.isFile() && (entry.name.endsWith('.ts') || entry.name.endsWith('.tsx'))) {
      out.push(full)
    }
  }
  return out
}

const hits = []
for (const dir of scanDirs) {
  for (const file of collectFiles(dir)) {
    if (file.endsWith(selfTestRelPath)) continue
    const lines = readFileSync(file, 'utf8').split('\n')
    lines.forEach((line, i) => {
      if (COMPLEXITY_DISABLE.test(line)) {
        hits.push(`${file.replace(frontendRoot + '/', '')}:${i + 1}`)
      }
    })
  }
}
const count = hits.length
let baseline = null
try {
  baseline = Number.parseInt(readFileSync(baselinePath, 'utf8').trim(), 10)
} catch {
  console.error(`error: baseline file not found at ${baselinePath}`)
  process.exit(1)
}

if (update) {
  if (count > baseline) {
    console.error(
      `error: refusing to raise the baseline: current count ${count} > baseline ${baseline}`,
    )
    console.error('Remove complexity disables to shrink the gate-off count, or edit the')
    console.error('baseline by hand as a deliberate, reviewed exception.')
    process.exit(1)
  }
  if (count < baseline) {
    writeFileSync(baselinePath, `${count}\n`)
    console.log(`ratcheted baseline down: ${baseline} -> ${count}`)
  } else {
    console.log(`baseline already at current count: ${count}`)
  }
  process.exit(0)
}

if (count > baseline) {
  console.error(
    `error: ${count} complexity-disable directives found, baseline is ${baseline}`,
  )
  console.error(
    'The complexity gate (eslint `complexity: [error, { max: 5 }]`) must only gain',
  )
  console.error(
    'coverage: refactor the new offenders and remove their disables instead (issue #532).',
  )
  process.exit(1)
}

console.log(`ok: ${count} complexity-disable directives (baseline ${baseline})`)
process.exit(0)
