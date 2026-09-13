/**
 * Utilities for matching MFA required API errors
 */

export const MFA_REQUIRED_MESSAGE = 'MFA required';

interface ErrorLike {
  message?: unknown;
  graphQLErrors?: Array<{ message?: unknown }>;
  errors?: Array<{ message?: unknown }>;
  networkError?: {
    message?: unknown;
    result?: {
      message?: unknown;
      errors?: Array<{ message?: unknown }>;
    };
  };
  detail?: {
    message?: unknown;
  };
}

export const isExactMfaMessage = (val: unknown): boolean =>
  typeof val === 'string' && val.trim() === MFA_REQUIRED_MESSAGE;

const checkItemMessage = (item: { message?: unknown }): boolean =>
  isExactMfaMessage(item.message);

const hasMfaInArray = (arr?: Array<{ message?: unknown }>): boolean =>
  Array.isArray(arr) && arr.some(checkItemMessage);

const checkNetworkResult = (result?: { message?: unknown; errors?: Array<{ message?: unknown }> }): boolean => {
  if (!result) return false;
  return isExactMfaMessage(result.message) || hasMfaInArray(result.errors);
};

const hasNetworkMfaError = (netErr?: ErrorLike['networkError']): boolean => {
  if (!netErr) return false;
  return isExactMfaMessage(netErr.message) || checkNetworkResult(netErr.result);
};

const hasDirectOrArrayMfa = (err: ErrorLike): boolean => {
  if (isExactMfaMessage(err.message)) return true;
  return hasMfaInArray(err.graphQLErrors) || hasMfaInArray(err.errors);
};

const hasDetailMfa = (detail?: { message?: unknown }): boolean =>
  Boolean(detail && isExactMfaMessage(detail.message));

const checkErrorObject = (err: ErrorLike): boolean => {
  if (hasDirectOrArrayMfa(err)) return true;
  return hasNetworkMfaError(err.networkError) || hasDetailMfa(err.detail);
};

/**
 * Checks if an error object or message matches the exact 'MFA required' error.
 */
export function isMfaRequiredError(error: unknown): boolean {
  if (!error) return false;
  if (isExactMfaMessage(error)) return true;
  if (typeof error !== 'object') return false;
  return checkErrorObject(error as ErrorLike);
}
