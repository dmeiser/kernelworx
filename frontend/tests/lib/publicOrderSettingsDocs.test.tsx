/**
 * Pins the settings-mutation wire contract.
 *
 * The server treats `campaignId` and `allowedPaymentMethods` as omit-to-keep:
 * the stored value survives only while the ARGUMENT IS ABSENT from the request,
 * and an explicit null is rejected with INVALID_INPUT. AppSync binds a
 * declared-but-unprovided nullable variable as an explicit null, so "keep" has
 * to be expressed by the DOCUMENT, not by the variables. These tests read the
 * documents the hook actually transmits (captured at the link, before the
 * network) and assert which argument and variable lines each one carries.
 */

import { describe, it, expect } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { ApolloClient, ApolloLink, InMemoryCache } from '@apollo/client';
import { ApolloProvider } from '@apollo/client/react';
import { MockLink } from '@apollo/client/testing';
import type { MockedResponse } from '@apollo/client/testing';
import type { DocumentNode, FieldNode, OperationDefinitionNode } from 'graphql';
import { usePublicOrderSettings } from '../../src/hooks/usePublicOrderSettings';
import {
  GET_MY_PAYMENT_METHODS,
  GET_PROFILE,
  GET_PROFILE_PUBLIC_ORDER_SETTINGS,
  LIST_CAMPAIGNS_BY_PROFILE,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS,
  UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
  pickUpdateProfilePublicOrderSettingsDoc,
} from '../../src/lib/graphql';

const DB_PROFILE_ID = 'PROFILE#p-1';

/** Argument names the document names on the mutation field. */
function argNames(doc: DocumentNode): string[] {
  const operation = doc.definitions.find(
    (definition): definition is OperationDefinitionNode => definition.kind === 'OperationDefinition',
  );
  const field = operation?.selectionSet.selections[0] as FieldNode | undefined;
  return (field?.arguments ?? []).map((argument) => argument.name.value);
}

/** Variable names the document declares. */
function declaredVariables(doc: DocumentNode): string[] {
  const operation = doc.definitions.find(
    (definition): definition is OperationDefinitionNode => definition.kind === 'OperationDefinition',
  );
  return (operation?.variableDefinitions ?? []).map((definition) => definition.variable.name.value);
}

/** What the mutation field selects: fields and fragment spreads, in order. */
function selectedFields(doc: DocumentNode): string[] {
  const operation = doc.definitions.find(
    (definition): definition is OperationDefinitionNode => definition.kind === 'OperationDefinition',
  );
  const field = operation?.selectionSet.selections[0] as FieldNode | undefined;
  return (field?.selectionSet?.selections ?? []).map((selection) => {
    if (selection.kind === 'Field') return selection.name.value;
    if (selection.kind === 'FragmentSpread') return `...${selection.name.value}`;
    return 'inline';
  });
}

describe('public-order settings mutation documents', () => {
  it('names the anchor campaign only in the enable/re-pick document', () => {
    expect(argNames(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR)).toContain('campaignId');
    expect(argNames(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS)).not.toContain('campaignId');
    expect(argNames(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED)).not.toContain('campaignId');
  });

  it('names the method list only where the save supplies one', () => {
    expect(argNames(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR)).toContain('allowedPaymentMethods');
    expect(argNames(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS)).toContain('allowedPaymentMethods');
    expect(argNames(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED)).not.toContain('allowedPaymentMethods');
  });

  it('declares no campaignId variable in the keep-case documents', () => {
    // A declared variable is what AppSync would bind to an explicit null.
    expect(declaredVariables(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR)).toContain('campaignId');
    expect(declaredVariables(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS)).not.toContain('campaignId');
    expect(declaredVariables(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED)).not.toContain('campaignId');
    expect(declaredVariables(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED)).not.toContain('allowedPaymentMethods');
  });

  it('selects the identical settings payload in every shape', () => {
    const anchor = selectedFields(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR);
    expect(selectedFields(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS)).toEqual(anchor);
    expect(selectedFields(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED)).toEqual(anchor);
    expect(anchor).toContain('...PublicOrderSettingsFields');
  });

  it('picks the document from the values the save will send', () => {
    expect(
      pickUpdateProfilePublicOrderSettingsDoc({ campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'] }),
    ).toBe(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR);
    expect(pickUpdateProfilePublicOrderSettingsDoc({ allowedPaymentMethods: ['Venmo'] })).toBe(
      UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS,
    );
    // An empty list is still a list: it clears the methods, it does not keep them.
    expect(pickUpdateProfilePublicOrderSettingsDoc({ allowedPaymentMethods: [] })).toBe(
      UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS,
    );
    // Rotate and disable carry neither omit-to-keep input, so nothing of the
    // published surface is named and a stale anchor cannot block them.
    expect(pickUpdateProfilePublicOrderSettingsDoc({})).toBe(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED);
    // A null never becomes an explicit null on the wire.
    expect(
      pickUpdateProfilePublicOrderSettingsDoc({ campaignId: null, allowedPaymentMethods: null }),
    ).toBe(UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED);
  });
});

// ---------------------------------------------------------------------------
// The same contract observed on the wire: the hook's request is captured at
// the link, so the assertion is on the transmitted document and variables.
// ---------------------------------------------------------------------------

const settingsBlob = (overrides: Record<string, unknown> = {}) => ({
  __typename: 'PublicOrderSettings',
  enabled: false,
  campaignId: null,
  campaignName: null,
  campaignState: null,
  allowedPaymentMethods: [],
  shareToken: null,
  publicOrderCount: null,
  acknowledgedAt: null,
  ackVersion: null,
  ...overrides,
});

const campaign = {
  __typename: 'Campaign',
  campaignId: 'CAMPAIGN#c-1',
  profileId: DB_PROFILE_ID,
  campaignName: 'Fall popcorn',
  campaignYear: 2026,
  startDate: '2026-09-01',
  endDate: '2026-12-01',
  catalogId: 'CATALOG#cat-1',
  unitType: 'Scouts BSA Troop',
  unitNumber: '42',
  city: 'Anytown',
  state: 'TX',
  sharedCampaignCode: null,
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  totalOrders: 3,
  totalRevenue: 40,
};

interface CapturedOperation {
  operationName: string;
  query: DocumentNode;
  variables: Record<string, unknown>;
}

/** A client whose link chain records every operation before it is sent. */
function wireClient(stored: Record<string, unknown>, mutation: MockedResponse) {
  const captured: CapturedOperation[] = [];
  const capture = new ApolloLink((operation, forward) => {
    captured.push({
      operationName: operation.operationName ?? '',
      query: operation.query,
      variables: (operation.variables ?? {}) as Record<string, unknown>,
    });
    return forward(operation);
  });
  const client = new ApolloClient({
    link: capture.concat(
      new MockLink([
        {
          request: { query: GET_PROFILE, variables: { profileId: DB_PROFILE_ID } },
          maxUsageCount: 10,
          result: {
            data: {
              getProfile: {
                __typename: 'SellerProfile',
                profileId: DB_PROFILE_ID,
                ownerAccountId: 'ACCOUNT#a-1',
                sellerName: 'Troop 42',
                createdAt: '2026-01-01T00:00:00Z',
                updatedAt: '2026-01-01T00:00:00Z',
                isOwner: true,
                permissions: [],
              },
            },
          },
        },
        {
          request: { query: GET_PROFILE_PUBLIC_ORDER_SETTINGS, variables: { profileId: DB_PROFILE_ID } },
          maxUsageCount: 10,
          result: { data: { getProfilePublicOrderSettings: stored } },
        },
        {
          request: { query: LIST_CAMPAIGNS_BY_PROFILE, variables: { profileId: DB_PROFILE_ID, limit: 100 } },
          maxUsageCount: 10,
          result: {
            data: { listCampaignsByProfile: { __typename: 'CampaignConnection', campaigns: [campaign], nextToken: null } },
          },
        },
        {
          request: { query: GET_MY_PAYMENT_METHODS },
          maxUsageCount: 10,
          result: {
            data: { myPaymentMethods: [{ __typename: 'PaymentMethod', name: 'Venmo', qrCodeUrl: 'qr-key' }] },
          },
        },
        mutation,
      ]),
    ),
    cache: new InMemoryCache(),
  });
  return { client, captured };
}

function renderSettingsClient(client: ApolloClient) {
  return renderHook(() => usePublicOrderSettings('p-1'), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <ApolloProvider client={client}>{children}</ApolloProvider>
    ),
  });
}

/** The one mutation the hook sent, by operation name. */
function sentMutation(captured: CapturedOperation[]) {
  const mutations = captured.filter((entry) => entry.operationName.startsWith('UpdateProfilePublicOrderSettings'));
  expect(mutations).toHaveLength(1);
  const sent = mutations[0];
  if (!sent) throw new Error('no settings mutation was transmitted');
  return sent;
}

describe('the settings save transmits the keep-case document', () => {
  it('disable names no campaign and no method list', async () => {
    const stored = settingsBlob({ enabled: true, campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'], shareToken: 'tok', ackVersion: 1 });
    const { client, captured } = wireClient(stored, {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: false },
      },
      result: { data: { updateProfilePublicOrderSettings: settingsBlob({ campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'], shareToken: 'tok', ackVersion: 1 }) } },
    });
    const { result } = renderSettingsClient(client);
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    await act(async () => {
      await result.current.disable();
    });

    const sent = sentMutation(captured);
    expect(sent.operationName).toBe('UpdateProfilePublicOrderSettingsParked');
    expect(argNames(sent.query)).not.toContain('campaignId');
    expect(argNames(sent.query)).not.toContain('allowedPaymentMethods');
    expect(sent.variables).not.toHaveProperty('campaignId');
    expect(sent.variables).not.toHaveProperty('allowedPaymentMethods');
    expect(result.current.actionMessage.kind).toBe('saved');
  });

  it('rotate-token names no campaign and no method list', async () => {
    const stored = settingsBlob({ enabled: true, campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'], shareToken: 'tok', ackVersion: 1 });
    const { client, captured } = wireClient(stored, {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_PARKED,
        variables: { profileId: DB_PROFILE_ID, enabled: true, rotateToken: true },
      },
      result: { data: { updateProfilePublicOrderSettings: settingsBlob({ enabled: true, campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'], shareToken: 'rotated', ackVersion: 1 }) } },
    });
    const { result } = renderSettingsClient(client);
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    await act(async () => {
      await result.current.rotateToken();
    });

    const sent = sentMutation(captured);
    expect(sent.operationName).toBe('UpdateProfilePublicOrderSettingsParked');
    expect(argNames(sent.query)).not.toContain('campaignId');
    expect(sent.variables).not.toHaveProperty('campaignId');
    expect(sent.variables.rotateToken).toBe(true);
    expect(result.current.actionMessage.kind).toBe('saved');
  });

  it('a method-list edit names the methods but never the stored campaign', async () => {
    const stored = settingsBlob({ enabled: true, campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: [], shareToken: 'tok', ackVersion: 1 });
    const { client, captured } = wireClient(stored, {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_METHODS,
        variables: { profileId: DB_PROFILE_ID, enabled: true, allowedPaymentMethods: ['Venmo'] },
      },
      result: { data: { updateProfilePublicOrderSettings: settingsBlob({ enabled: true, campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'], shareToken: 'tok', ackVersion: 1 }) } },
    });
    const { result } = renderSettingsClient(client);
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    act(() => {
      result.current.toggleMethod('Venmo', true);
    });
    await act(async () => {
      await result.current.save();
    });

    const sent = sentMutation(captured);
    expect(sent.operationName).toBe('UpdateProfilePublicOrderSettingsMethods');
    expect(argNames(sent.query)).not.toContain('campaignId');
    expect(argNames(sent.query)).toContain('allowedPaymentMethods');
    expect(sent.variables).not.toHaveProperty('campaignId');
    expect(sent.variables.allowedPaymentMethods).toEqual(['Venmo']);
    expect(result.current.actionMessage.kind).toBe('saved');
  });

  it('enabling names the campaign it publishes', async () => {
    const stored = settingsBlob();
    const { client, captured } = wireClient(stored, {
      request: {
        query: UPDATE_PROFILE_PUBLIC_ORDER_SETTINGS_ANCHOR,
        variables: {
          profileId: DB_PROFILE_ID,
          enabled: true,
          campaignId: 'CAMPAIGN#c-1',
          allowedPaymentMethods: ['Venmo'],
          acknowledgementsAccepted: true,
        },
      },
      result: { data: { updateProfilePublicOrderSettings: settingsBlob({ enabled: true, campaignId: 'CAMPAIGN#c-1', allowedPaymentMethods: ['Venmo'], shareToken: 'tok', ackVersion: 1 }) } },
    });
    const { result } = renderSettingsClient(client);
    await waitFor(() => expect(result.current.settingsLoaded).toBe(true));

    act(() => {
      result.current.setEnabled(true);
      result.current.setCampaignId('CAMPAIGN#c-1');
      result.current.toggleMethod('Venmo', true);
      result.current.setAck('ackPayment', true);
      result.current.setAck('ackDisclosure', true);
    });
    await act(async () => {
      await result.current.save();
    });

    const sent = sentMutation(captured);
    expect(sent.operationName).toBe('UpdateProfilePublicOrderSettingsAnchor');
    expect(argNames(sent.query)).toContain('campaignId');
    expect(sent.variables.campaignId).toBe('CAMPAIGN#c-1');
    expect(result.current.actionMessage.kind).toBe('saved');
  });
});
