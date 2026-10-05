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
 *
 * State model: every settings action runs through one page-wide controller
 * bound to the profile identity and a monotonic request generation, and a
 * response is applied only while both still mark it live (a later request
 * shadows an earlier one, and an in-flight action can never repaint another
 * profile's page). One outcome judge decides what a response means: a thrown
 * or rejected request, an abort, a returned error object, and GraphQL errors
 * riding a resolved response (the main client reads with errorPolicy:'all')
 * are ALL failure. Exactly one mutating request may be in flight, and every
 * mutating control stays disabled and visibly pending for the whole span of
 * that request (mutation + refresh + reconcile). One owner decides when the
 * draft may be replaced. Success derives from the mutation's own returned
 * blob, never from the follow-up refresh; a failed refresh is a separate
 * retryable notice that neither overwrites a true success nor repaints a
 * failed action, and the server-confirmed blob stays the authoritative stored
 * view until the query catches up. The 'saved' confirmation dies as soon as
 * the seller edits the draft and an unsaved-changes indicator takes its
 * place, while an unedited refetch keeps it.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
  draftMatchesSavedView,
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
  | { kind: 'unsaved' }
  | { kind: 'failed'; message: string };

/** The shape a settings response is judged against, whatever way it arrives. */
interface SettingsResponse {
  data?: { updateProfilePublicOrderSettings: PublicOrderSettingsView | null } | null;
  errors?: readonly unknown[];
  error?: unknown;
}

/** A judged settings response. */
interface SettingsOutcome {
  failure: unknown;
  view: PublicOrderSettingsView | null;
}

/** One in-flight action's scope: identity + generation gate and its release. */
interface ActionSpan {
  profileId: string;
  isLive: () => boolean;
  release: () => void;
}

/** Keeps an action's returned blob authoritative until a newer read lands. */
interface SavedSnapshot {
  /** The settings read the write raced with; a newer read wins. */
  seen: unknown;
  view: PublicOrderSettingsView;
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

/**
 * The ONE outcome judge for every settings request: a thrown/rejected request
 * or an abort arrives as `thrown`; a returned error object is `result.error`;
 * GraphQL errors riding a resolved response (the main client reads with
 * errorPolicy:'all') arrive as `result.errors`. All three are failure, and so
 * is a response without the saved settings payload.
 */
const EMPTY_SETTINGS_RESPONSE_MESSAGE = 'The settings write returned no data.';

function judgeMutation(thrown: unknown, result: SettingsResponse | null | undefined): SettingsOutcome {
  const failure = settingsRequestFailure(thrown, result);
  if (failure !== null) return { failure, view: null };
  return judgeMutationPayload(result);
}

function judgeMutationPayload(result: SettingsResponse | null | undefined): SettingsOutcome {
  const data = result?.data;
  const view = data ? data.updateProfilePublicOrderSettings ?? null : null;
  if (view !== null) return { failure: null, view };
  return { failure: new Error(EMPTY_SETTINGS_RESPONSE_MESSAGE), view: null };
}

function settingsRequestFailure(
  thrown: unknown,
  result: { errors?: readonly unknown[]; error?: unknown } | null | undefined,
): unknown {
  if (thrown) return thrown;
  if (result?.error) return result.error;
  return firstSettingsError(result);
}

function firstSettingsError(result: { errors?: readonly unknown[] } | null | undefined): unknown {
  if (!result) return null;
  const errors = result.errors ?? [];
  return errors.at(0) ?? null;
}

const settingsFailureMessage = (failure: unknown): string =>
  mapErrorCodeToMessage(getErrorCode(failure), getErrorMessage(failure));

/**
 * The ONE draft owner's inputs. 'seed' fully re-derives the draft from stored
 * settings (first load of a profile identity); 'action' reconciles exactly the
 * fields the action transmitted, so the form agrees with the persisted state
 * while unrelated unsaved edits survive; a plain refetch passes through the
 * same owner ('refetch') and re-derives nothing.
 */
type DraftRequest =
  | { type: 'seed'; view: PublicOrderSettingsView | null }
  | { type: 'action'; args: SettingsSaveArgs; view: PublicOrderSettingsView | null }
  | { type: 'refetch' };

/** Loads a transmitted field from the saved view, keeping the stored one otherwise. */
function loadTransmitted(
  transmitted: boolean,
  saved: string | null | undefined,
  fallback: string,
): string {
  if (!transmitted) return fallback;
  return saved ?? '';
}

function loadTransmittedMethods(
  transmitted: boolean,
  saved: readonly string[] | null | undefined,
  fallback: string[],
): string[] {
  if (!transmitted) return [...fallback];
  return [...(saved ?? [])];
}

function nextDraft(previous: SettingsDraft, request: DraftRequest): SettingsDraft {
  if (request.type === 'refetch') return previous;
  const view = request.view ?? EMPTY_PUBLIC_ORDER_SETTINGS;
  if (request.type === 'seed') return draftFromSettings(view);
  return {
    ...previous,
    enabled: view.enabled === true,
    campaignId: loadTransmitted(request.args.campaignId !== undefined, view.campaignId, previous.campaignId),
    methods: loadTransmittedMethods(
      request.args.allowedPaymentMethods !== undefined,
      view.allowedPaymentMethods,
      previous.methods,
    ),
  };
}

/** The confirmation never survives the seller's own edit to the draft. */
function derivedActionMessage(state: SettingsActionMessage, diverged: boolean): SettingsActionMessage {
  if (state.kind !== 'saved') return state;
  if (state.refreshFailed || !diverged) return state;
  return { kind: 'unsaved' };
}

/** The saved blob is authority until a newer read lands; a failed refresh keeps it. */
function liveSnapshot(snapshot: SavedSnapshot | null, data: unknown): PublicOrderSettingsView | null {
  if (!snapshot) return null;
  if (snapshot.seen !== data) return null;
  return snapshot.view;
}

/** The stored view: the live saved snapshot when it holds, the query read otherwise. */
function freshestSettings(
  saved: PublicOrderSettingsView | null,
  read: PublicOrderSettingsView | null,
): PublicOrderSettingsView {
  if (saved) return saved;
  return read ?? EMPTY_PUBLIC_ORDER_SETTINGS;
}

/** A hard settings error is one where the page never loaded. */
function loadError(error: unknown, everLoaded: boolean): unknown {
  if (!error || everLoaded) return null;
  return error;
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

  // The controller: the live profile identity (synced to the route), the
  // monotonic generation of settings requests, and the single in-flight slot.
  const identityRef = useRef('');
  useLayoutEffect(() => {
    identityRef.current = dbProfileId;
  }, [dbProfileId]);
  const requestSeqRef = useRef(0);
  const inFlightRef = useRef(false);
  const [submitting, setSubmitting] = useState(false);

  // The freshest settings snapshot is the stored view: a successful action's
  // returned blob stays authority until the query produces a read newer than
  // the one the write raced with (i.e. the post-action refresh landed); if
  // that refresh fails, the server-confirmed blob keeps the page on truth.
  const [savedSnapshot, setSavedSnapshot] = useState<SavedSnapshot | null>(null);
  const savedActive = liveSnapshot(savedSnapshot, settings.data);
  const stored = freshestSettings(savedActive, readSettings(settings.data));
  const [draft, setDraft] = useState<SettingsDraft>(() => draftFromSettings(stored));
  const [seededProfileId, setSeededProfileId] = useState<string | null>(null);
  const [actionState, setActionState] = useState<SettingsActionMessage>({ kind: 'idle' });

  const reconcileDraft = useCallback(
    (request: DraftRequest) => setDraft((previous) => nextDraft(previous, request)),
    [],
  );

  // Seed from stored settings exactly once per saved profile identity and
  // reset the action feedback with it: a response for a previous profile may
  // not repaint this one.
  useEffect(() => {
    if (!settings.data) return;
    if (seededProfileId === dbProfileId) return;
    setSeededProfileId(dbProfileId);
    setActionState({ kind: 'idle' });
    reconcileDraft({ type: 'seed', view: readSettings(settings.data) });
  }, [settings.data, dbProfileId, seededProfileId, reconcileDraft]);

  // A hard settings error means the page never loaded; a refresh failure after
  // a loaded page must degrade to the refresh notice, not tear the form down.
  // The marker is per profile identity: A's success must not suppress B's
  // hard failure in the settings error below.
  const [everLoaded, setEverLoaded] = useState(false);
  useEffect(() => {
    if (settings.data) setEverLoaded(true);
  }, [settings.data]);
  // Layout phase so a cache-warm identity switch (settings.data already
  // present for the new profile) resets BEFORE the data effect re-arms it.
  useLayoutEffect(() => {
    setEverLoaded(false);
  }, [dbProfileId]);
  const settingsError = loadError(settings.error, everLoaded) as Error | null;

  const [updateSettings] = useMutation<
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

  const startSpan = (ownerProfileId: string): ActionSpan => {
    const request = ++requestSeqRef.current;
    const isLive = () => identityRef.current === ownerProfileId && requestSeqRef.current === request;
    inFlightRef.current = true;
    return {
      profileId: ownerProfileId,
      isLive,
      release: () => {
        if (requestSeqRef.current !== request) return;
        inFlightRef.current = false;
        setSubmitting(false);
      },
    };
  };

  const saveOutcome = async (issue: () => Promise<SettingsResponse>): Promise<SettingsOutcome> => {
    try {
      return judgeMutation(null, await issue());
    } catch (thrown) {
      return { failure: thrown, view: null };
    }
  };

  /**
   * The one serialization point for every settings action: exactly one action
   * spans its mutation, refresh and reconcile, and a call issued while one is
   * outstanding is dropped. Nothing is applied after the action's identity or
   * generation stops being the live one.
   */
  const run = async (args: SettingsSaveArgs) => {
    if (inFlightRef.current) return;
    const span = startSpan(dbProfileId);
    setSubmitting(true);
    setActionState({ kind: 'idle' });

    const outcome = await saveOutcome(() => updateSettings({ variables: { profileId: span.profileId, ...args } }));
    if (span.isLive()) await applyOutcome(span, args, outcome);
    span.release();
  };

  /** Applies the judged outcome — success, failure or a dropped one. */
  const applyOutcome = async (span: ActionSpan, args: SettingsSaveArgs, outcome: SettingsOutcome) => {
    const view = outcome.view;
    if (!view) {
      setActionState({ kind: 'failed', message: settingsFailureMessage(outcome.failure) });
      return;
    }
    setSavedSnapshot({ seen: settings.data ?? null, view });
    reconcileDraft({ type: 'action', args, view });
    setActionState({ kind: 'saved', refreshFailed: false });

    const refreshFailed = await refreshViaQuery(span);
    if (span.isLive()) setActionState({ kind: 'saved', refreshFailed });
  };

  /** The follow-up refresh: its failure (rejected, aborted or errored result) never invalidates the action's own success. */
  const refreshViaQuery = async (span: ActionSpan): Promise<boolean> => {
    if (!span.isLive()) return false;
    try {
      const refreshed = await settings.refetch();
      if (!span.isLive()) return false;
      return settingsRequestFailure(null, refreshed) !== null;
    } catch (thrown) {
      if (!span.isLive()) return false;
      return settingsRequestFailure(thrown, null) !== null;
    }
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
      campaignId: pickCampaignArg(enabling, repicking, draft.campaignId),
      allowedPaymentMethods: draft.methods,
      acknowledgementsAccepted: pickAcksArg(acksRequired, acksChecked),
    });
  };

  const rotateToken = async () => run({ enabled: stored.enabled, rotateToken: true });
  const disable = async () => run({ enabled: false });

  const diverged = !draftMatchesSavedView(draft, stored);
  const message = derivedActionMessage(actionState, diverged);

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
    actionMessage: message,
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

/** An anchor is transmitted only to enable or to re-pick — never otherwise. */
function pickCampaignArg(enabling: boolean, repicking: boolean, campaignId: string): string | undefined {
  if (!enabling && !repicking) return undefined;
  return campaignId || undefined;
}

/** The acknowledgement stamp is sent exactly when the gate asks for it. */
function pickAcksArg(required: boolean, checked: boolean): true | undefined {
  if (!required || !checked) return undefined;
  return true;
}
