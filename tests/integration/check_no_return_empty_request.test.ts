import { describe, test, expect } from 'vitest';
import { readdirSync, readFileSync } from 'fs';
import { join } from 'path';

const RESOLVERS_DIR = join(__dirname, '..', '..', 'cdk', 'cdk', 'appsync', 'js-resolvers');

// Passthrough functions that use None data source legitimately return {} from request()
// These just process data already in ctx.stash without making DynamoDB calls
const PASSTHROUGH_FUNCTIONS = new Set([
  'check_payment_methods_access_fn.js',
  'filter_payment_methods_by_access_fn.js',
  'get_payment_method_for_delete_fn.js',
  'inject_global_payment_methods_fn.js',
  'inspect_put_item_fn.js',
  'log_create_order_state_fn.js',
  'return_campaign_fn.js',
  'return_order_fn.js',
  'sanitize_order_item_fn.js',
  'validate_create_payment_method_fn.js',
  'validate_update_payment_method_fn.js',
]);

describe('AppSync resolver functions should not return empty object from request()', () => {
  const files = readdirSync(RESOLVERS_DIR).filter(f => f.endsWith('.js'));

  for (const file of files) {
    // Only check files that are function implementations (naming convention: *_fn.js)
    if (!file.endsWith('_fn.js')) continue;
    
    // Skip known passthrough functions (use None data source)
    if (PASSTHROUGH_FUNCTIONS.has(file)) continue;

    test(`${file} should not return {} from request()`, () => {
      const content = readFileSync(join(RESOLVERS_DIR, file), 'utf8');
      const hasBadReturn = /export function request\([^)]*\)\s*\{[\s\S]*?return\s*\{\s*\}/m.test(content);
      expect(hasBadReturn).toBe(false);
    });
  }
});
