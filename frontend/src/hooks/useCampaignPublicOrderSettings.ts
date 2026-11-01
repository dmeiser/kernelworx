/**
 * Data and actions for one campaign's public order settings.
 *
 * Provides queries to fetch the campaign's stored public order configuration
 * and the seller's available payment methods. Exposes mutations for saving
 * configuration, rotating the share token, enabling public orders, and
 * disabling public orders.
 *
 * Maintains the server-confirmed settings, an editable draft for seller changes,
 * dirty and saved indicators, and acknowledgement checkbox states.
 * Mutation errors are captured in hook state to surface actionable feedback to the user.
 * In-flight mutation state (updating) is managed exclusively within the mutation lifecycle.
 * Draft changes are preserved across query refetches.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useApolloClient, useQuery } from '@apollo/client/react';
import type { ErrorLike } from '@apollo/client';
import {
  GET_MY_PAYMENT_METHODS,
  GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
  UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
} from '../lib/graphql';
import { isNotFoundError } from '../lib/api-utils';
import { ensureCampaignId } from '../lib/ids';
import type {
  GqlGetCampaignPublicOrderSettingsQuery,
  GqlGetMyPaymentMethodsQuery,
  GqlUpdateCampaignPublicOrderSettingsInput,
  GqlUpdateCampaignPublicOrderSettingsMutation,
} from '../types/graphql-generated';

export const PUBLIC_ORDER_ACK_VERSION = 1;

export type PublicOrderOperation = 'save' | 'rotate' | 'enable' | 'disable';

export interface PublicOrderMutationError {
  operation: PublicOrderOperation;
  message: string;
  error?: unknown;
}

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
  /** Settings query error, if any. */
  queryError?: ErrorLike;
  /** Refetch the settings query. */
  refetch?: () => Promise<unknown>;
  /** Whether the settings query failed with NOT_FOUND. */
  isNotFound?: boolean;
  /** Mutation error from save/rotate/enable/disable, if any. */
  mutationError: PublicOrderMutationError | null;
  /** Clear the active mutation error. */
  clearMutationError: () => void;
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
  ...emptySettings,
};

interface UseCampaignPublicOrderSettingsArgs {
  campaignId: string | null;
}

type RawSettings = NonNullable<GqlGetCampaignPublicOrderSettingsQuery['getCampaignPublicOrderSettings']>;
type RawUpdated = NonNullable<GqlUpdateCampaignPublicOrderSettingsMutation['updateCampaignPublicOrderSettings']>;

/** Whether the server-stored acknowledgement timestamp and version count as validly accepted. */
function hasValidAcknowledgement(
  acknowledgedAt: string | null | undefined,
  ackVersion: number | null | undefined,
): boolean {
  return !!acknowledgedAt && acknowledgedAt !== '' && ackVersion === PUBLIC_ORDER_ACK_VERSION;
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

/** Map a mutation response blob into the view shape. */
function mapUpdatedToView(updated: RawUpdated): PublicOrderSettingsView {
  return {
    ...mapIdentityFields(updated),
    token: updated.shareToken ?? null,
    allowedPaymentMethods: updated.allowedPaymentMethods ?? [],
    acknowledgedAt: updated.acknowledgedAt ?? null,
    ackVersion: updated.ackVersion ?? null,
  };
}

/** Payment method names offered to the seller, with Cash and Check always present. */
function buildAvailablePaymentMethods(paymentMethods: { name: string }[]): string[] {
  return Array.from(new Set([...paymentMethods.map((method) => method.name), 'Cash', 'Check']));
}

function extractErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function useCampaignPublicOrderSettings({
  campaignId,
}: UseCampaignPublicOrderSettingsArgs): CampaignPublicOrderSettingsState {
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
  const [mutationError, setMutationError] = useState<PublicOrderMutationError | null>(null);

  const acknowledgementsAccepted = paymentAckAccepted && disclosureAckAccepted;

  const clearMutationError = useCallback(() => {
    setMutationError(null);
  }, []);

  /** Apply a stored acknowledgement timestamp and version to both checkbox states. */
  const applyAcknowledged = useCallback(
    (acknowledgedAt: string | null | undefined, ackVersion: number | null | undefined) => {
      const accepted = hasValidAcknowledgement(acknowledgedAt, ackVersion);
      setPaymentAckAccepted(accepted);
      setDisclosureAckAccepted(accepted);
    },
    [],
  );

  // Fetch settings
  const {
    data: settingsData,
    loading,
    error: queryError,
    refetch,
  } = useQuery<GqlGetCampaignPublicOrderSettingsQuery>(GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS, {
    variables: { campaignId: dbCampaignId },
    fetchPolicy: 'network-only',
    skip: !dbCampaignId,
    errorPolicy: 'all',
  });

  // Fetch payment methods
  const { data: paymentMethodsData } = useQuery<GqlGetMyPaymentMethodsQuery>(GET_MY_PAYMENT_METHODS, {
    skip: !dbCampaignId,
  });

  const dirtyRef = useRef(false);
  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  // Initialize or update the stored view from the settings query.
  // Preserves unsaved draft state across background refetches.
  useEffect(() => {
    const fetched = settingsData?.getCampaignPublicOrderSettings;
    if (!fetched) {
      return;
    }
    const mapped = mapFetchedToView(fetched);
    setSettings(mapped);

    if (!dirtyRef.current) {
      setDraft(mapped);
      setSaved(true);
      applyAcknowledged(fetched.acknowledgedAt, fetched.ackVersion);
    }
  }, [settingsData, applyAcknowledged]);

  // The available method list follows the payment-methods query.
  useEffect(() => {
    const paymentMethods = paymentMethodsData?.myPaymentMethods ?? [];
    setAvailablePaymentMethods(buildAvailablePaymentMethods(paymentMethods));
  }, [paymentMethodsData]);

  const setField = useCallback(
    (field: PublicOrderSettingsField, value: string | boolean | string[] | null) => {
      setDirty(true);
      setDraft((previous) => ({ ...previous, [field]: value }));
    },
    [setDraft, setDirty],
  );

  const applyUpdated = useCallback(
    (updated: RawUpdated) => {
      const mapped = mapUpdatedToView(updated);
      setSettings(mapped);
      setDraft(mapped);
      setSaved(true);
      setDirty(false);
      applyAcknowledged(updated.acknowledgedAt, updated.ackVersion);
    },
    [applyAcknowledged],
  );

  const mutateSettings = async (
    operation: PublicOrderOperation,
    campaignKey: string,
    buildInput: (id: string) => GqlUpdateCampaignPublicOrderSettingsInput,
  ) => {
    setUpdating(true);
    setMutationError(null);
    try {
      const result = await apolloClient.mutate<GqlUpdateCampaignPublicOrderSettingsMutation>({
        mutation: UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS,
        variables: { input: buildInput(campaignKey) },
      });
      if (result.error) {
        throw result.error;
      }
      if (result.data?.updateCampaignPublicOrderSettings) {
        applyUpdated(result.data.updateCampaignPublicOrderSettings);
      }
    } catch (updateError) {
      setMutationError({
        operation,
        message: extractErrorMessage(updateError),
        error: updateError,
      });
    } finally {
      setUpdating(false);
    }
  };

  const save = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(
      'save',
      dbCampaignId,
      (id) =>
        ({
          campaignId: id,
          enabled: draft.enabled,
          allowedPaymentMethods: draft.allowedPaymentMethods,
          acknowledgementsAccepted: acknowledgementsAccepted,
        }) as GqlUpdateCampaignPublicOrderSettingsInput,
    );
  };

  const rotateToken = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(
      'rotate',
      dbCampaignId,
      (id) =>
        ({
          campaignId: id,
          enabled: draft.enabled,
          allowedPaymentMethods: draft.allowedPaymentMethods,
          acknowledgementsAccepted: acknowledgementsAccepted,
          rotateToken: true,
        }) as GqlUpdateCampaignPublicOrderSettingsInput,
    );
  };

  const disable = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(
      'disable',
      dbCampaignId,
      (id) =>
        ({
          campaignId: id,
          enabled: false,
          allowedPaymentMethods: draft.allowedPaymentMethods,
        }) as GqlUpdateCampaignPublicOrderSettingsInput,
    );
  };

  const enable = async () => {
    if (!dbCampaignId) return;
    await mutateSettings(
      'enable',
      dbCampaignId,
      (id) =>
        ({
          campaignId: id,
          enabled: true,
          allowedPaymentMethods: draft.allowedPaymentMethods,
          acknowledgementsAccepted: acknowledgementsAccepted,
        }) as GqlUpdateCampaignPublicOrderSettingsInput,
    );
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
    save,
    rotateToken,
    disable,
    enable,
    paymentAckAccepted,
    setPaymentAckAccepted,
    disclosureAckAccepted,
    setDisclosureAckAccepted,
    acknowledgementsAccepted,
    queryError,
    refetch,
    isNotFound: isNotFoundError(queryError),
    mutationError,
    clearMutationError,
  };
}
