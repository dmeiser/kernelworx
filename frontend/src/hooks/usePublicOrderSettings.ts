/**
 * Data and actions for one profile's public order settings.
 *
 * The mutation's argument semantics are pinned server-side and mirrored here:
 * an OMITTED `campaignId`/`allowedPaymentMethods` keeps the stored value, while
 * an explicit `null` is rejected with INVALID_INPUT — so a save never sends a
 * null it did not mean. `rotateToken` is the only revocation path and is legal
 * while the feature is parked (disabled).
 */

import { useEffect, useMemo, useState } from 'react';
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

  const stored = readSettings(settings.data);
  const [draft, setDraft] = useState<SettingsDraft>(() => draftFromSettings(stored));
  const [savedOnce, setSavedOnce] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(draftFromSettings(readSettings(settings.data)));
  }, [settings.data]);

  const [updateSettings, { loading: submitting }] = useMutation<
    GqlUpdateProfilePublicOrderSettingsMutation,
    GqlUpdateProfilePublicOrderSettingsMutationVariables
  >(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS);

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

  const run = async (args: SettingsSaveArgs) => {
    setActionError(null);
    try {
      await updateSettings({ variables: { profileId: dbProfileId, ...args } });
      setSavedOnce(true);
      await settings.refetch();
    } catch (error) {
      setActionError(mapErrorCodeToMessage(getErrorCode(error), getErrorMessage(error)));
    }
  };

  const save = async () =>
    run({
      enabled: draft.enabled,
      campaignId: draft.campaignId || undefined,
      allowedPaymentMethods: draft.methods,
      acknowledgementsAccepted: acksRequired && acksChecked ? true : undefined,
    });

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
    savedOnce,
    actionError,
    settingsLoaded: Boolean(settings.data),
    settingsError: settings.error,
    setEnabled,
    setCampaignId,
    setAck,
    toggleMethod,
    save,
    rotateToken,
    disable,
  };
}
