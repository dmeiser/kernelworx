import { defineConfig } from 'vitest/config';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    name: 'guards',
    root: __dirname,
    globals: true,
    environment: 'node',
    include: [path.resolve(__dirname, 'tests/unit/**/*.test.ts')],
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      // Python test support files are not TypeScript tests
      '**/tests/unit/conftest.py',
      '**/tests/unit/fixtures.py',
      '**/tests/unit/table_schemas.py',
    ],
  },
});
