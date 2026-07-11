import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';

const RESOLVERS_DIR = join(__dirname, '..', '..', 'tofu', 'application', 'appsync', 'js-resolvers');

describe('AppSync resolver functions should not return empty object from request()', () => {
  const files = readdirSync(RESOLVERS_DIR).filter(f => f.endsWith('.js'));

  for (const file of files) {
    // Only check files that are function implementations (naming convention: *_fn.js)
    if (!file.endsWith('_fn.js')) continue;

    test(`${file} should not return {} from request()`, () => {
      const content = readFileSync(join(RESOLVERS_DIR, file), 'utf8');
      const hasBadReturn = /export function request\([^)]*\)\s*\{[\s\S]*?return\s*\{\s*\}/m.test(content);
      expect(hasBadReturn).toBe(false);
    });
  }
});
