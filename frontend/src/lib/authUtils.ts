/**
 * Utilities for Cognito authentication session and identity claims
 */

import { fetchAuthSession, signOut, type AuthSession } from 'aws-amplify/auth';

export interface FederatedIdentity {
  userId?: string;
  providerName?: string;
  providerType?: string;
  issuer?: string | null;
  primary?: boolean;
  dateCreated?: number | string;
}

const isValidIdentityItem = (item: unknown): boolean => {
  if (typeof item !== 'object' || item === null) return false;
  const providerName = (item as { providerName?: unknown }).providerName;
  return typeof providerName === 'string' && providerName.trim().length > 0;
};

const parseIdentitiesJson = (raw: string): unknown => {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
};

const normalizeIdentities = (raw: unknown): unknown => {
  if (typeof raw === 'string') {
    return parseIdentitiesJson(raw);
  }
  return raw;
};

/**
 * Checks if the identities claim represents a federated (social/IdP) identity.
 *
 * Federated users in Cognito have an `identities` claim that is a non-empty array
 * of identity objects with a valid `providerName` (either parsed or as a JSON string).
 * Native Cognito users have no `identities` claim.
 */
export function isFederatedIdentitiesClaim(identities: unknown): boolean {
  if (!identities) return false;
  const normalized = normalizeIdentities(identities);
  if (!Array.isArray(normalized) || normalized.length === 0) return false;
  return normalized.some(isValidIdentityItem);
}

/**
 * Checks if a JWT token payload contains a federated identities claim.
 */
export function isFederatedTokenPayload(payload: unknown): boolean {
  if (typeof payload !== 'object' || payload === null) return false;
  const identities = (payload as { identities?: unknown }).identities;
  return isFederatedIdentitiesClaim(identities);
}

/**
 * Checks if an Amplify AuthSession represents a federated user session.
 */
export function isFederatedSession(session: unknown): boolean {
  if (typeof session !== 'object' || session === null) return false;
  const s = session as AuthSession;
  const payload = s.tokens?.idToken?.payload;
  return isFederatedTokenPayload(payload);
}

/**
 * Fetches the current auth session and checks if it is a federated session.
 */
export async function checkIsFederatedSession(): Promise<boolean> {
  try {
    const session = await fetchAuthSession();
    return isFederatedSession(session);
  } catch {
    return false;
  }
}

/**
 * Attempts global sign out with fallback to local sign out
 */
export async function attemptSignOut(): Promise<void> {
  try {
    await signOut({ global: true });
  } catch {
    try {
      await signOut();
    } catch {
      // Ignored: sign out attempt handled
    }
  }
}

/**
 * Signs the user out and redirects to the login page
 */
export async function handleSignOutAndRedirect(): Promise<void> {
  await attemptSignOut();
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
}
