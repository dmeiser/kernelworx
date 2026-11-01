import { describe, test, expect } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';

const CANONICAL = 'send_order_emails';
const __dirname = fileURLToPath(new URL('.', import.meta.url));

describe('send_order_emails discriminator contract', () => {
  test('JS constant matches canonical', () => {
    const src = readFileSync(join(__dirname, '..', '..', 'tofu', 'application', 'appsync', 'js-resolvers', 'send_public_order_emails_fn.js'), 'utf8');
    const m = src.match(/export const SEND_ORDER_EMAILS_OPERATION = '([^']+)'/);
    expect(m).not.toBeNull();
    expect(m![1]).toBe(CANONICAL);
  });

  test('Python constant matches canonical', () => {
    const src = readFileSync(join(__dirname, '..', '..', 'src', 'handlers', 'public_order_emails.py'), 'utf8');
    const m = src.match(/SEND_ORDER_EMAILS_OPERATION = "([^"]+)"/);
    expect(m).not.toBeNull();
    expect(m![1]).toBe(CANONICAL);
  });
});
