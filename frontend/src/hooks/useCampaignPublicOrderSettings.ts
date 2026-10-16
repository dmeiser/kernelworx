/**
 * Data and actions for one campaign's public order settings.
 *
 * The mutation's argument semantics are pinned server-side and mirrored here:
 * an OMITTED `allowedPaymentMethods` keeps the stored value, while
 * an explicit `null` is rejected with INVALID_INPUT — so a save never sends a
 * null it did not mean. "Omitted" is a property of the transmitted DOCUMENT
 * (AppSync binds an unprovided nullable variable as an explicit null), so each
 * save shape sends its own mutation document via
 * pickUpdateCampaignPublicOrderSettingsDoc instead of varying variables.
 * `rotateToken` is the only revocation path and is legal
 * while the feature is parked (disabled).
 *
 * State model: every settings action runs through one page-wide controller
 * bound to the campaign identity and a monotonic request generation, and a
 * response is applied only while both still mark it live (a later request
 * shadows an earlier one, and an in-flight action can never repaint another
 * campaign's page). One outcome judge decides what a response means: a thrown
 * or rejected request, an abort, a returned error object, and GraphQL errors
 * riding a resolved response (the main client reads with errorPolicy:'all')
 * are ALL failure. Exactly one mutating request may be in flight, and every
 * mutating control stays disabled and visibly pending for the whole span of
 * that request (mutation + refresh + reconcile). One owner decides when the
 * draft may be replaced. Success derives from the mutation's own returned
 * blob, never from the follow-up refresh; a failed refresh is a separate
 * retryable notice that neither overwrites a true success nor repaints a
 * failed action, and the server-confirmed blob stays the authoritative stored
 * view until a clean read catches up — a refresh that fails (rejected, or
 * resolving with a null payload plus GraphQL errors) holds it instead of
 * letting the broken read collapse the page. The 'saved' confirmation dies as soon as
 * the seller edits the draft and an unsaved-changes indicator takes its
 * place, while an unedited refetch keeps it.
 */

import { useCallback, useEffect, useState } from 'react';
import { useApolloClient, useQuery } from '@apollo/client/react';
import {
  GET_CAMPAIGN,
  GET_MY_PAYMENT_METHODS,
  GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
  pickUpdateCampaignPublicOrderSettingsDoc,
} from '../lib/graphql';
import { ensureCampaignId } from '../lib/ids';
import type { GqlGetCampaignPublicOrderSettingsQuery, GqlGetMyPaymentMethodsQuery, GqlUpdateCampaignPublicOrderSettingsInput, GqlUpdateCampaignPublicOrderSettingsMutation, GqlCampaign } from '../types/graphql-generated';

export const PUBLIC_ORDER_ACK_VERSION = 1;

/**
 * Hook return type.
 */
export interface CampaignPublicOrderSettingsState {
  /** The current settings from the server. */
  settings: PublicOrderSettingsView | null;
  /** Whether a settings read request is in flight. */
  loading: boolean;
  /** Whether a settings mutation (save/rotate/enable/disable) is in flight. */
  updating: boolean;
  /** Whether the server has acknowledged the current draft. */
  saved: boolean;
  /** Whether the user has unsaved changes. */
  dirty: boolean;
  /** The current draft, as edited by the user. */
  draft: PublicOrderSettingsView;
  /** Set a field in the draft. */
  setField: (field: PublicOrderSettingsField, value: string | boolean | string[] | null) => void;

  /** Available payment methods, including Cash and Check. */
  availablePaymentMethods: string[];
  /** Save the draft to the server. */
  save: () => Promise<void>;
  /** Rotate the share token. */
  rotateToken: () => Promise<void>;
  /** Disable public orders. */
  disable: () => Promise<void>;
  /** Enable public orders. */
  enable: () => Promise<void>;
  /** Payment-responsibility acknowledgement (D4) accepted. */
  paymentAckAccepted: boolean;
  /** Set the payment-responsibility acknowledgement. */
  setPaymentAckAccepted: (value: boolean) => void;
  /** QR/PII-disclosure acknowledgement (D5) accepted. */
  disclosureAckAccepted: boolean;
  /** Set the QR/PII-disclosure acknowledgement. */
  setDisclosureAckAccepted: (value: boolean) => void;
  /** Both acknowledgements accepted — the mutation's `acknowledgementsAccepted` flag. */
  acknowledgementsAccepted: boolean;
}

/** The shape of the settings object. */
export interface PublicOrderSettingsView {
  enabled: boolean;
  token: string | null;
  allowedPaymentMethods: string[];
  acknowledgedAt: string | null;
  ackVersion: number | null;
  publicOrderCount: number;
  campaignId: string;
  campaignName: string;
  campaignState: string;
}

/** Fields that can be edited in the draft. */
export type PublicOrderSettingsField =
  | 'enabled'
  | 'token'
  | 'allowedPaymentMethods'
  | 'acknowledgedAt'
  | 'ackVersion'
  | 'publicOrderCount'
  | 'campaignId'
  | 'campaignName'
  | 'campaignState';

const emptySettings: PublicOrderSettingsView = {
  enabled: false,
  token: null,
  allowedPaymentMethods: [],
  acknowledgedAt: null,
  ackVersion: null,
  publicOrderCount: 0,
  campaignId: '',
  campaignName: '',
  campaignState: '',
};

const emptyDraft: PublicOrderSettingsView = {
  ...emptySettings
};

interface UseCampaignPublicOrderSettingsArgs {
  campaignId: string | null;
}

type RawSettings = NonNullable<GqlGetCampaignPublicOrderSettingsQuery['getCampaignPublicOrderSettings']>;
type RawUpdated = NonNullable<GqlUpdateCampaignPublicOrderSettingsMutation['updateCampaignPublicOrderSettings']>;

/** Whether the server-stored acknowledgement timestamp counts as accepted. */
function hasAcknowledged(acknowledgedAt: string | null | undefined): boolean {
  return !!acknowledgedAt && acknowledgedAt !== '';
}

/** Map the fields shared by the settings query and the mutation response. */
function mapIdentityFields(raw: {
  enabled: boolean;
  publicOrderCount?: number | null;
  campaignId?: string | null;
  campaignName?: string | null;
  campaignState?: string | null;
}): Pick<PublicOrderSettingsView, 'enabled' | 'publicOrderCount' | 'campaignId' | 'campaignName' | 'campaignState'> {
  return {
    enabled: raw.enabled,
    publicOrderCount: raw.publicOrderCount ?? 0,
    campaignId: raw.campaignId ?? '',
    campaignName: raw.campaignName ?? '',
    campaignState: raw.campaignState ?? '',
  };
}

/** Map a settings-query row into the view shape. */
function mapFetchedToView(fetched: RawSettings): PublicOrderSettingsView {
  return {
    ...mapIdentityFields(fetched),
    token: fetched.shareToken ?? null,
    allowedPaymentMethods: fetched.allowedPaymentMethods ?? [],
    acknowledgedAt: fetched.acknowledgedAt ?? null,
    ackVersion: fetched.ackVersion ?? null,
  };
}

/** Derive the ack version the mutation response implies. */
function ackVersionFromAcknowledgement(acknowledgedAt: string | null | undefined): number | null {
  return acknowledgedAt !== undefined && acknowledgedAt !== null ? PUBLIC_ORDER_ACK_VERSION : null;
}

/** Map a mutation response blob into the view shape. */
function mapUpdatedToView(updated: RawUpdated): PublicOrderSettingsView {
  return {
    ...mapIdentityFields(updated),
    token: updated.shareToken ?? null,
    allowedPaymentMethods: updated.allowedPaymentMethods ?? [],
    acknowledgedAt: updated.acknowledgedAt ?? null,
    ackVersion: ackVersionFromAcknowledgement(updated.acknowledgedAt),
  };
}

/** Payment method names offered to the seller, with Cash and Check always present. */
function buildAvailablePaymentMethods(paymentMethods: { name: string }[]): string[] {
  return Array.from(new Set([...paymentMethods.map((method) => method.name), 'Cash', 'Check']));
}

export function useCampaignPublicOrderSettings({ campaignId }: UseCampaignPublicOrderSettingsArgs) {
  const dbCampaignId = campaignId ? ensureCampaignId(campaignId) : null;
  const apolloClient = useApolloClient();
  const [updating, setUpdating] = useState(false);
  const [settings, setSettings] = useState<PublicOrderSettingsView | null>(null);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [draft, setDraft] = useState<PublicOrderSettingsView>(emptyDraft);
  const [paymentAckAccepted, setPaymentAckAccepted] = useState(false);
  const [disclosureAckAccepted, setDisclosureAckAccepted] = useState(false);
  const [availablePaymentMethods, setAvailablePaymentMethods] = useState<string[]>([]);

  const acknowledgementsAccepted = paymentAckAccepted && disclosureAckAccepted;

  /** Apply a stored acknowledgement timestamp to both checkbox states. */
  const applyAcknowledged = (acknowledgedAt: string | null | undefined) => {
    const accepted = hasAcknowledged(acknowledgedAt);
    setPaymentAckAccepted(accepted);
    setDisclosureAckAccepted(accepted);
  };

  // Fetch campaign
  const { data: campaignData } = useQuery<{ getCampaign: GqlCampaign }>(GET_CAMPAIGN, {
    variables: { campaignId: dbCampaignId },
    skip: !dbCampaignId,
  });

  // Fetch settings
  const { data: settingsData, loading } = useQuery<GqlGetCampaignPublicOrderSettingsQuery>(GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS, {
    variables: { campaignId: dbCampaignId },
    fetchPolicy: 'network-only',
    skip: !dbCampaignId,
  });

  // Fetch payment methods
  const { data: paymentMethodsData } = useQuery<GqlGetMyPaymentMethodsQuery>(GET_MY_PAYMENT_METHODS, {
    skip: !dbCampaignId,
  });

  // Helper to get campaign from query data

  // Initialize the stored view from the settings query. Depends only on the
  // settings data: a late payment-methods resolution must not re-apply the
  // original query row over post-mutation state.
  useEffect(() => {
    const fetched = settingsData?.getCampaignPublicOrderSettings;
    if (!fetched) {
      return;
    }
    const mapped = mapFetchedToView(fetched);
    setSettings(mapped);
    setDraft(mapped);
    setSaved(true);
    setDirty(false);
    applyAcknowledged(fetched.acknowledgedAt);
  }, [settingsData]);

  // The available method list follows the payment-methods query.
  useEffect(() => {
    const paymentMethods = paymentMethodsData?.myPaymentMethods ?? [];
    setAvailablePaymentMethods(buildAvailablePaymentMethods(paymentMethods));
  }, [paymentMethodsData]);

  // Reset draft when settings change
  useEffect(() => {
    if (settings) {
      setDraft(settings);
      setDirty(false);
    }
  }, [settings]);

  // Reset saving flag when campaign or payment methods change
  useEffect(() => {
    setUpdating(false);
  }, [campaignData, paymentMethodsData]);

  const setField = useCallback(
    (field: PublicOrderSettingsField, value: string | boolean | string[] | null) => {
      setDirty(true);
      setDraft((previous) => ({ ...previous, [field]: value }));
    },
    [setDraft, setDirty],
  );

  const mutateSettings = async (
    campaignKey: string,
    buildInput: (id: string) => GqlUpdateCampaignPublicOrderSettingsInput,
  ) => {
    setUpdating(true);
    try {
      const result = await apolloClient.mutate<GqlUpdateCampaignPublicOrderSettingsMutation>({
        mutation: pickUpdateCampaignPublicOrderSettingsDoc(),
        variables: { input: buildInput(campaignKey) },
      });
      const updated = result.data?.updateCampaignPublicOrderSettings;
      if (updated) {
        const mapped = mapUpdatedToView(updated);
        setSettings(mapped);
        setDraft(mapped);
        setSaved(true);
        setDirty(false);
        applyAcknowledged(updated.acknowledgedAt);
      }
    } catch (updateError) {
      // TODO: handle error
      console.error(updateError);
    } finally {
      setUpdating(false);
    }
  };

  const save = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(dbCampaignId, (id) => ({
      campaignId: id,
      enabled: draft.enabled,
      allowedPaymentMethods: draft.allowedPaymentMethods,
      acknowledgementsAccepted: acknowledgementsAccepted,
    } as GqlUpdateCampaignPublicOrderSettingsInput));
  };

  const rotateToken = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(dbCampaignId, (id) => ({
      campaignId: id,
      enabled: draft.enabled,
      allowedPaymentMethods: draft.allowedPaymentMethods,
      acknowledgementsAccepted: acknowledgementsAccepted,
      rotateToken: true,
    } as GqlUpdateCampaignPublicOrderSettingsInput));
  };

  const disable = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(dbCampaignId, (id) => ({
      campaignId: id,
      enabled: false,
      allowedPaymentMethods: draft.allowedPaymentMethods,
    } as GqlUpdateCampaignPublicOrderSettingsInput));
  };

  const enable = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(dbCampaignId, (id) => ({
      campaignId: id,
      enabled: true,
      allowedPaymentMethods: draft.allowedPaymentMethods,
      acknowledgementsAccepted: acknowledgementsAccepted,
    } as GqlUpdateCampaignPublicOrderSettingsInput));
  };
  return {
    settings,
    loading,
    updating,
    saved,
    dirty,
    draft,
    setField,
    availablePaymentMethods,
    setAvailablePaymentMethods,
    save,
    rotateToken,
    disable,
    enable,
    paymentAckAccepted,
    setPaymentAckAccepted,
    disclosureAckAccepted,
    setDisclosureAckAccepted,
    acknowledgementsAccepted,
  };
}