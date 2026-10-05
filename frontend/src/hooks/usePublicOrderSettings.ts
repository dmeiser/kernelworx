/**
 * Data and actions for one profile's public order settings.
 *
 * The mutation's argument semantics are pinned server-side and mirrored here:
 * an OMITTED `campaignId`/`allowedPaymentMethods` keeps the stored value, while
 * an explicit `null` is rejected with INVALID_INPUT — so a save never sends a
 * null it did not mean. `rotateToken` is the only revocation path and is legal
 * while the feature is parked (disabled). Anchor enforcement only applies to
 * enabling and to picking/re-picking a campaign, so a save only names
 * `campaignId` when it enables the feature or changes the picked campaign —
 * method-list edits, rotate and disable keep working while the stored anchor
 * has gone stale.
 */

import { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  GET_MY_PAYMENT_METHODS,
  GET_PROFILE,
  GET_PROFILE_PUBLIC_ORDER_SETTINGS,
  LIST_CAMPAIGNS_BY_PROFILE,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS,
} from '../lib/graphql';
import { ensureProfileId } from '../lib/ids';
import { getErrorCode, getErrorMessage } from '../lib/api-utils';
import { mapErrorCodeToMessage } from '../lib/apollo';
import {
  EMPTY_PUBLIC_ORDER_SETTINGS,
  buildMethodOptions,
  draftFromSettings,
  type PublicOrderSettingsView,
  type SettingsDraft,
} from '../lib/publicOrderSettings';
import { acknowledgementIsBehind } from '../constants/publicOrders';
import type {
  GqlCampaign,
  GqlPaymentMethod,
  GqlUpdateProfilePublicOrderSettingsMutation,
  GqlUpdateProfilePublicOrderSettingsMutationVariables,
} from '../types/graphql-generated';

/** Variables for one settings save; omitted fields keep their stored value. */
export interface SettingsSaveArgs {
  enabled: boolean;
  campaignId?: string;
  allowedPaymentMethods?: string[];
  acknowledgementsAccepted?: boolean;
  rotateToken?: boolean;
}

/** The status of the last settings action, rendered by PublicSettingsMessages. */
export type SettingsActionMessage =
  | { kind: 'idle' }
  | { kind: 'saved'; refreshFailed: boolean }
  | { kind: 'failed'; message: string };

interface ProfileView {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
}

type SettingsQueryData = { getProfilePublicOrderSettings: PublicOrderSettingsView | null } | undefined;
type ProfileQueryData = { getProfile: ProfileView } | undefined;
type CampaignsQueryData = { listCampaignsByProfile: { campaigns: GqlCampaign[] } } | undefined;
type MethodsQueryData = { myPaymentMethods: GqlPaymentMethod[] } | undefined;

/** Unwrap the settings query result (a never-enabled profile is null, not an error). */
function readSettings(data: SettingsQueryData): PublicOrderSettingsView {
  return data?.getProfilePublicOrderSettings ?? EMPTY_PUBLIC_ORDER_SETTINGS;
}

function readProfile(data: ProfileQueryData): ProfileView | null {
  return data?.getProfile ?? null;
}

/** Only ACTIVE campaigns are offerable as an anchor; the server enforces the same. */
function readActiveCampaigns(data: CampaignsQueryData): GqlCampaign[] {
  return (data?.listCampaignsByProfile.campaigns ?? []).filter((campaign) => campaign.isActive !== false);
}

function readMethodNames(data: MethodsQueryData): string[] {
  return (data?.myPaymentMethods ?? []).map((method) => method.name);
}

/** Save is blocked in flight and while required acknowledgements are incomplete. */
export function computeSaveDisabled(args: { submitting: boolean; acksRequired: boolean; acksChecked: boolean }): boolean {
  return args.submitting || (args.acksRequired && !args.acksChecked);
}

export function usePublicOrderSettings(profileId: string) {
  const dbProfileId = ensureProfileId(profileId) ?? '';
  const skip = !dbProfileId;

  const profile = useQuery<{ getProfile: ProfileView }>(GET_PROFILE, { variables: { profileId: dbProfileId }, skip });
  const settings = useQuery<{ getProfilePublicOrderSettings: PublicOrderSettingsView | null }>(
    GET_PROFILE_PUBLIC_ORDER_SETTINGS,
    { variables: { profileId: dbProfileId }, skip },
  );
  const campaigns = useQuery<{ listCampaignsByProfile: { campaigns: GqlCampaign[] } }>(LIST_CAMPAIGNS_BY_PROFILE, {
    variables: { profileId: dbProfileId, limit: 100 },
    skip,
  });
  const paymentMethods = useQuery<{ myPaymentMethods: GqlPaymentMethod[] }>(GET_MY_PAYMENT_METHODS, { skip });

  // The freshest settings snapshot is the stored view: a successful action's
  // returned blob is authority until the post-action refetch lands a newer
  // query snapshot; if that refetch fails, the returned blob keeps the page on
  // the truth the server just confirmed.
  const queryDataRef = useRef<unknown>(null);
  const savedRef = useRef<PublicOrderSettingsView | null>(null);
  if (settings.data !== queryDataRef.current) {
    queryDataRef.current = settings.data;
    savedRef.current = null;
  }
  const stored = savedRef.current ?? readSettings(settings.data);
  const [draft, setDraft] = useState<SettingsDraft>(() => draftFromSettings(stored));
  const [seededProfileId, setSeededProfileId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<SettingsActionMessage>({ kind: 'idle' });

  /**
   * The ONE place stored settings flow into the draft. `args === null` is the
   * full first-load seed of a profile; after a successful action it reconciles
   * exactly the fields that action transmitted, so the form always agrees with
   * the persisted state while unrelated unsaved edits survive.
   */
  const refreshDraft = (args: SettingsSaveArgs | null, view: PublicOrderSettingsView | null) =>
    setDraft((previous) => {
      const settingsView = view ?? EMPTY_PUBLIC_ORDER_SETTINGS;
      if (args === null) return draftFromSettings(settingsView);
      return {
        ...previous,
        enabled: settingsView.enabled === true,
        campaignId: args.campaignId !== undefined ? settingsView.campaignId ?? '' : previous.campaignId,
        methods: args.allowedPaymentMethods !== undefined ? settingsView.allowedPaymentMethods ?? [] : previous.methods,
      };
    });

  // Seed (or re-seed for another profile) from stored settings exactly once per
  // saved profile: an action-triggered refetch must not clobber unsaved draft
  // edits.
  if (settings.data && seededProfileId !== dbProfileId) {
    setSeededProfileId(dbProfileId);
    refreshDraft(null, readSettings(settings.data));
  }

  // A hard settings error means the page never loaded; a refetch failure after
  // a loaded page must degrade to the refresh notice, not tear the form down.
  const loadedRef = useRef(false);
  if (settings.data) loadedRef.current = true;
  const settingsError = settings.error && !loadedRef.current ? settings.error : null;

  const [updateSettings] = useMutation<
    GqlUpdateProfilePublicOrderSettingsMutation,
    GqlUpdateProfilePublicOrderSettingsMutationVariables
  >(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS);
  /** True for the whole action span: mutation + refetch + reconcile. */
  const [submitting, setSubmitting] = useState(false);
  const inFlightRef = useRef(false);

  const activeCampaigns = useMemo(() => readActiveCampaigns(campaigns.data), [campaigns.data]);
  const methodOptions = useMemo(() => buildMethodOptions(readMethodNames(paymentMethods.data)), [paymentMethods.data]);

  const acksRequired = draft.enabled && acknowledgementIsBehind(stored.ackVersion);
  const acksChecked = draft.ackPayment && draft.ackDisclosure;

  const setEnabled = (enabled: boolean) => setDraft((previous) => ({ ...previous, enabled }));
  const setCampaignId = (campaignId: string) => setDraft((previous) => ({ ...previous, campaignId }));
  const setAck = (field: 'ackPayment' | 'ackDisclosure', value: boolean) =>
    setDraft((previous) => ({ ...previous, [field]: value }));

  const toggleMethod = (name: string, checked: boolean) =>
    setDraft((previous) => ({
      ...previous,
      methods: checked
        ? [...previous.methods, name]
        : previous.methods.filter((entry) => entry.toLowerCase() !== name.toLowerCase()),
    }));

  /**
   * The serialization point for every settings action: exactly one action spans
   * its mutation, refetch and reconcile, and a call issued while one is
   * outstanding is dropped. Success derives from the mutation's own result; a
   * failed refresh is a separate, retryable notice that never overwrites a
   * success nor repaints a failure.
   */
  const run = async (args: SettingsSaveArgs) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setSubmitting(true);
    setActionMessage({ kind: 'idle' });
    let saved = false;
    let refreshFailed = false;
    try {
      const result = await updateSettings({ variables: { profileId: dbProfileId, ...args } });
      const savedView = result.data?.updateProfilePublicOrderSettings ?? null;
      if (savedView) {
        savedRef.current = savedView;
        refreshDraft(args, savedView);
      }
      saved = true;
      try {
        await settings.refetch();
      } catch {
        refreshFailed = true;
      }
    } catch (error) {
      setActionMessage({
        kind: 'failed',
        message: mapErrorCodeToMessage(getErrorCode(error), getErrorMessage(error)),
      });
    }
    if (saved) {
      setActionMessage({ kind: 'saved', refreshFailed });
    }
    inFlightRef.current = false;
    setSubmitting(false);
  };

  // Save names campaignId only when this save enables the feature or changes
  // the picked campaign: anchor enforcement is deliberate server-side, and a
  // method-list edit or a disable while the anchor is stale must not be
  // dragged into it. An omitted campaignId keeps the stored value.
  const save = async () => {
    const enabling = draft.enabled && !stored.enabled;
    const repicking = Boolean(draft.campaignId) && draft.campaignId !== (stored.campaignId ?? '');
    return run({
      enabled: draft.enabled,
      campaignId: enabling || repicking ? draft.campaignId || undefined : undefined,
      allowedPaymentMethods: draft.methods,
      acknowledgementsAccepted: acksRequired && acksChecked ? true : undefined,
    });
  };

  const rotateToken = async () => run({ enabled: stored.enabled, rotateToken: true });
  const disable = async () => run({ enabled: false });

  return {
    dbProfileId,
    profile: readProfile(profile.data),
    stored,
    activeCampaigns,
    methodOptions,
    draft,
    acksRequired,
    acksChecked,
    saveDisabled: computeSaveDisabled({ submitting, acksRequired, acksChecked }),
    submitting,
    actionMessage,
    settingsLoaded: Boolean(settings.data),
    settingsError,
    setEnabled,
    setCampaignId,
    setAck,
    toggleMethod,
    save,
    rotateToken,
    disable,
  };
}
