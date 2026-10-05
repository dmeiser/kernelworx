/**
 * Pure helpers for the per-profile public order settings surface.
 *
 * Kept out of the page module so the page file exports only components
 * (react-refresh) and so the case-insensitive method matching — which the
 * server applies too — is unit-testable on its own.
 */

import type { GqlPublicOrderSettings } from '../types';

/** Method names a buyer can be allowed to pick even without a QR upload. */
export const GLOBAL_PAYMENT_METHODS: readonly string[] = ['Cash', 'Check'];

/** The settings fields the page renders. */
export type PublicOrderSettingsView = Pick<
  GqlPublicOrderSettings,
  'enabled' | 'campaignId' | 'campaignName' | 'campaignState' | 'allowedPaymentMethods' | 'shareToken' | 'publicOrderCount' | 'ackVersion'
>;

/** Local edit state for one profile's public order settings. */
export interface SettingsDraft {
  enabled: boolean;
  campaignId: string;
  methods: string[];
  ackPayment: boolean;
  ackDisclosure: boolean;
}

/** Case-insensitive membership: the server matches method names the same way. */
export function methodIsAllowed(allowed: readonly string[], name: string): boolean {
  const lower = name.toLowerCase();
  return allowed.some((candidate) => candidate.toLowerCase() === lower);
}

/** A never-enabled profile: the server returns enabled false with nulls. */
export const EMPTY_PUBLIC_ORDER_SETTINGS: PublicOrderSettingsView = {
  enabled: false,
  campaignId: null,
  campaignName: null,
  campaignState: null,
  allowedPaymentMethods: [],
  shareToken: null,
  publicOrderCount: null,
  ackVersion: null,
};

/** Draft seeded from stored settings. Both acknowledgement boxes start empty. */
export function draftFromSettings(settings: PublicOrderSettingsView | null): SettingsDraft {
  const source = settings ?? EMPTY_PUBLIC_ORDER_SETTINGS;
  return {
    enabled: source.enabled === true,
    campaignId: source.campaignId ?? '',
    methods: source.allowedPaymentMethods ?? [],
    ackPayment: false,
    ackDisclosure: false,
  };
}

/** Case-insensitive list equality: the server matches method names the same way. */
function sameMethods(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const names = new Set(b.map((name) => name.toLowerCase()));
  return a.every((name) => names.has(name.toLowerCase()));
}

/**
 * True while the draft equals the state the server last confirmed: the gate
 * that turns a 'saved' confirmation into the unsaved-changes indicator. The
 * acknowledgement checkboxes are transient prompts and are not persisted
 * fields, so they take no part in the comparison.
 */
export function draftMatchesSavedView(draft: SettingsDraft, view: PublicOrderSettingsView | null): boolean {
  const saved = draftFromSettings(view);
  if (draft.enabled !== saved.enabled) return false;
  if (draft.campaignId !== saved.campaignId) return false;
  return sameMethods(draft.methods, saved.methods);
}

/** Method options: the account's stored methods plus Cash/Check, deduped case-insensitively. */
export function buildMethodOptions(storedNames: readonly string[]): string[] {
  const extras = GLOBAL_PAYMENT_METHODS.filter(
    (name) => !storedNames.some((existing) => existing.toLowerCase() === name.toLowerCase()),
  );
  return [...storedNames, ...extras];
}
