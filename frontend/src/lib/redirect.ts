/**
 * Redirect validation utilities
 */

/**
 * Validates that a redirect target is a same-origin relative path.
 * Only accepts strings that start with a single '/' and do not include a host.
 */
export function isSafeRedirect(path: string): boolean {
  if (typeof path !== 'string') return false;
  if (!path.startsWith('/')) return false;
  if (path.startsWith('//')) return false;
  if (path.includes('\\')) return false;
  return true;
}

/**
 * Returns a safe redirect path, or the fallback if the input is not valid.
 */
export function getSafeRedirect(path: string | null | undefined, fallback: string): string {
  if (path && isSafeRedirect(path)) {
    return path;
  }
  return fallback;
}

function formatQuery(search: unknown): string {
  if (typeof search !== 'string' || search.length === 0) return '';
  return search.startsWith('?') ? search : `?${search}`;
}

function resolvePathFromObject(fromValue: unknown): string | undefined {
  if (!fromValue || typeof fromValue !== 'object') return undefined;
  const { pathname, search } = fromValue as { pathname?: unknown; search?: unknown };
  if (typeof pathname !== 'string') return undefined;
  if (pathname.includes('?')) return pathname;
  return `${pathname}${formatQuery(search)}`;
}

/**
 * Resolves a redirect path from router location state, preserving query parameters.
 */
export function resolveRedirectFromState(state: unknown): string | undefined {
  if (!state || typeof state !== 'object') return undefined;
  const fromValue = (state as { from?: unknown }).from;
  if (typeof fromValue === 'string') return fromValue;
  return resolvePathFromObject(fromValue);
}

