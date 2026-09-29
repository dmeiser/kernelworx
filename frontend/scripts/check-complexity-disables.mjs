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
 * This script counts the directives under the source directory (default:
 * `src/`), compares the count to the committed baseline in
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
const srcDir = srcDirArg
  ? isAbsolute(srcDirArg)
    ? srcDirArg
    : resolve(join(dirname(fileURLToPath(import.meta.url)), '..', srcDirArg))
  : resolve(join(dirname(fileURLToPath(import.meta.url)), '..', 'src'))
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
for (const file of collectFiles(srcDir)) {
  const lines = readFileSync(file, 'utf8').split('\n')
  lines.forEach((line, i) => {
    if (COMPLEXITY_DISABLE.test(line)) {
      hits.push(`${file.replace(resolve(join(here, '..')) + '/', '')}:${i + 1}`)
    }
  })
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
    'coverage: refactor the new offenders and remove their disables instead. See',
  )
  console.error('the frontend complexity gate note in AGENTS.md and issue #532.')
  process.exit(1)
}

console.log(`ok: ${count} complexity-disable directives (baseline ${baseline})`)
process.exit(0)
