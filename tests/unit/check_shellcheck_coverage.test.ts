import { describe, it, expect } from 'vitest';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const ROOT_DIR = join(__dirname, '..', '..');

/**
 * The CI `shellcheck` job lists every gated script explicitly. This test keeps
 * that list in sync with the tracked scripts and keeps the gate honest: no
 * script may escape it by omission, the shellcheck image must stay pinned, and
 * no script may blanket-disable rules for its whole file.
 */
function trackedShellScripts(): string[] {
  const out = execFileSync('git', ['ls-files', '*.sh'], {
    cwd: ROOT_DIR,
    encoding: 'utf8',
  });
  return out
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith('node_modules/') && !line.includes('/node_modules/'));
}

function ciShellcheckJobBlock(): string {
  const ci = readFileSync(join(ROOT_DIR, '.github', 'workflows', 'ci.yml'), 'utf8');
  const start = ci.search(/^ {2}shellcheck:$/m);
  expect(start, 'CI must define a `shellcheck` job').toBeGreaterThan(-1);
  const rest = ci.slice(start);
  const nextJob = rest.slice(1).search(/^ {2}[A-Za-z0-9_-]+:$/m);
  return nextJob === -1 ? rest : rest.slice(0, nextJob + 1);
}

describe('shellcheck gate coverage (#759)', () => {
  const jobBlock = ciShellcheckJobBlock();

  it('gates every tracked repo-owned shell script by explicit path', () => {
    const gated = [...jobBlock.matchAll(/(?:^|\s)([\w./-]+\.sh)(?=\s)/g)].map((m) => m[1]);
    expect(gated.length, 'the shellcheck job must list at least one script').toBeGreaterThan(0);
    expect(new Set(gated).size, 'the shellcheck job lists a script twice').toBe(gated.length);
    expect(gated.sort()).toEqual(trackedShellScripts().sort());
  });

  it('pins the shellcheck image to an exact version tag', () => {
    const image = jobBlock.match(/([A-Za-z0-9._/-]*shellcheck:[^\s\\]+)/);
    expect(image, 'the shellcheck job must run a shellcheck container image').not.toBeNull();
    expect(image![1]).toMatch(/:v\d+\.\d+\.\d+$/);
    // A severity downgrade would silently drop findings from the gate.
    expect(jobBlock).not.toMatch(/--severity|--enable=|--exclude=/);
  });

  it('no script blanket-disables rules for the whole file', () => {
    for (const script of trackedShellScripts()) {
      const head = readFileSync(join(ROOT_DIR, script), 'utf8').split('\n').slice(0, 3).join('\n');
      expect(head, `${script} carries a file-level shellcheck disable directive`).not.toMatch(/shellcheck disable=/);
    }
  });
});
