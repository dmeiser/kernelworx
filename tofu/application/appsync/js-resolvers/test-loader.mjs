import { pathToFileURL } from 'node:url';
import { dirname, resolve as resolvePath } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const mockUrl = pathToFileURL(resolvePath(__dirname, '__mocks__/@aws-appsync/utils.js')).href;

export function resolve(specifier, context, nextResolve) {
  if (specifier === '@aws-appsync/utils') {
    return { shortCircuit: true, url: mockUrl };
  }
  return nextResolve(specifier, context);
}
