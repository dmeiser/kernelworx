/**
 * Utilities for detecting Cognito native AMR claim and handling session dismissal.
 */

export const isAdminUser = (payload: Record<string, unknown> | undefined): boolean => {
  const groups = payload?.['cognito:groups'];
  const list = Array.isArray(groups) ? groups : typeof groups === 'string' ? [groups] : [];
  return list.includes('ADMIN');
};

export const hasAmrClaim = (payload: Record<string, unknown> | undefined): boolean => {
  if (!payload || typeof payload !== 'object') {
    return false;
  }
  return Object.hasOwn(payload, 'amr') && payload['amr'] !== undefined;
};

export const shouldShowAmrBanner = (payload: Record<string, unknown> | undefined): boolean => {
  return isAdminUser(payload) && hasAmrClaim(payload);
};

export const getSessionDismissKey = (payload: Record<string, unknown> | undefined): string => {
  const sessionId = payload?.jti ?? payload?.auth_time;
  return sessionId ? `amr_tripwire_dismissed_${sessionId}` : 'amr_tripwire_dismissed';
};

export const isSessionDismissed = (key: string): boolean => {
  try {
    return typeof sessionStorage !== 'undefined' && sessionStorage.getItem(key) === 'true';
  } catch {
    return false;
  }
};

export const markSessionDismissed = (key: string): void => {
  try {
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem(key, 'true');
    }
  } catch {
    // Ignore storage failures
  }
};

export const getActiveTripwireKey = (payload: Record<string, unknown> | undefined): string | null => {
  if (!shouldShowAmrBanner(payload)) {
    return null;
  }
  const key = getSessionDismissKey(payload);
  return isSessionDismissed(key) ? null : key;
};

export const resolveActiveKeyFromSession = (session: unknown): string | null => {
  const s = session as { tokens?: { idToken?: { payload?: Record<string, unknown> } } } | undefined;
  return getActiveTripwireKey(s?.tokens?.idToken?.payload);
};
