/**
 * Utilities for matching MFA required API errors
 *
 * The backend emits ErrorCode.MFA_REQUIRED (#451) in the GraphQL error
 * extensions; matching the exact 'MFA required' message string is kept
 * only as a fallback for errors that lack the code.
 */

export const MFA_REQUIRED_MESSAGE = 'MFA required';
export const MFA_REQUIRED_ERROR_CODE = 'MFA_REQUIRED';

interface ErrorExtensions {
  errorCode?: unknown;
  code?: unknown;
  errorType?: unknown;
}

interface ErrorItem {
  message?: unknown;
  extensions?: ErrorExtensions;
}

interface NetworkResult {
  message?: unknown;
  errors?: ErrorItem[];
}

interface ErrorLike {
  message?: unknown;
  extensions?: ErrorExtensions;
  graphQLErrors?: ErrorItem[];
  errors?: ErrorItem[];
  networkError?: {
    message?: unknown;
    result?: NetworkResult;
  };
  detail?: {
    message?: unknown;
    errorCode?: unknown;
  };
}

export const isExactMfaMessage = (val: unknown): boolean =>
  typeof val === 'string' && val.trim() === MFA_REQUIRED_MESSAGE;

export const isMfaErrorCode = (val: unknown): boolean => val === MFA_REQUIRED_ERROR_CODE;

const hasMfaCodeInExtensions = (extensions?: ErrorExtensions): boolean =>
  [extensions?.errorCode, extensions?.code, extensions?.errorType].some(isMfaErrorCode);

const checkItem = (item: ErrorItem): boolean =>
  hasMfaCodeInExtensions(item.extensions) || isExactMfaMessage(item.message);

const hasMfaInArray = (arr?: ErrorItem[]): boolean => Array.isArray(arr) && arr.some(checkItem);

const checkNetworkResult = (result?: NetworkResult): boolean => {
  if (!result) return false;
  return isExactMfaMessage(result.message) || hasMfaInArray(result.errors);
};

const hasNetworkMfaError = (netErr?: ErrorLike['networkError']): boolean => {
  if (!netErr) return false;
  return isExactMfaMessage(netErr.message) || checkNetworkResult(netErr.result);
};

const hasDirectOrArrayMfa = (err: ErrorLike): boolean => {
  if (hasMfaCodeInExtensions(err.extensions) || isExactMfaMessage(err.message)) return true;
  return hasMfaInArray(err.graphQLErrors) || hasMfaInArray(err.errors);
};

const hasDetailMfa = (detail?: ErrorLike['detail']): boolean =>
  Boolean(detail && (isMfaErrorCode(detail.errorCode) || isExactMfaMessage(detail.message)));

const checkErrorObject = (err: ErrorLike): boolean => {
  if (hasDirectOrArrayMfa(err)) return true;
  return hasNetworkMfaError(err.networkError) || hasDetailMfa(err.detail);
};

/**
 * Checks if an error object or message matches the MFA required error,
 * keyed on the stable MFA_REQUIRED error code with the exact
 * 'MFA required' message as a fallback.
 */
export function isMfaRequiredError(error: unknown): boolean {
  if (!error) return false;
  if (isExactMfaMessage(error)) return true;
  if (typeof error !== 'object') return false;
  return checkErrorObject(error as ErrorLike);
}
