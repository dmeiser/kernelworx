/**
 * Tests for the settings helpers: case-insensitive method matching (the server
 * matches the same way), the draft seeded from stored settings, and the
 * acknowledgement version gate that drives the re-prompt.
 */

import { describe, it, expect } from 'vitest';
import {
  EMPTY_PUBLIC_ORDER_SETTINGS,
  GLOBAL_PAYMENT_METHODS,
  buildMethodOptions,
  draftFromSettings,
  methodIsAllowed,
} from '../../src/lib/publicOrderSettings';
import {
  PUBLIC_ORDER_ACKNOWLEDGEMENTS,
  PUBLIC_ORDER_ACK_VERSION,
  PUBLIC_ORDER_CAP,
  acknowledgementIsBehind,
} from '../../src/constants/publicOrders';

describe('methodIsAllowed', () => {
  it('matches case-insensitively', () => {
    expect(methodIsAllowed(['Venmo'], 'venmo')).toBe(true);
    expect(methodIsAllowed(['CASH'], 'Cash')).toBe(true);
  });

  it('rejects a name that is not on the list', () => {
    expect(methodIsAllowed(['Venmo'], 'Cash')).toBe(false);
    expect(methodIsAllowed([], 'Venmo')).toBe(false);
  });
});

describe('draftFromSettings', () => {
  it('starts both acknowledgements unchecked even when the store has accepted them', () => {
    const draft = draftFromSettings({ ...EMPTY_PUBLIC_ORDER_SETTINGS, enabled: true, ackVersion: PUBLIC_ORDER_ACK_VERSION });
    expect(draft.ackPayment).toBe(false);
    expect(draft.ackDisclosure).toBe(false);
  });

  it('seeds enabled, campaign and methods from stored settings', () => {
    const draft = draftFromSettings({
      ...EMPTY_PUBLIC_ORDER_SETTINGS,
      enabled: true,
      campaignId: 'CAMPAIGN#abc',
      allowedPaymentMethods: ['Venmo', 'Cash'],
    });
    expect(draft).toEqual({
      enabled: true,
      campaignId: 'CAMPAIGN#abc',
      methods: ['Venmo', 'Cash'],
      ackPayment: false,
      ackDisclosure: false,
    });
  });

  it('treats a never-enabled profile as disabled with nothing selected', () => {
    expect(draftFromSettings(null)).toEqual({
      enabled: false,
      campaignId: '',
      methods: [],
      ackPayment: false,
      ackDisclosure: false,
    });
  });

  it('treats a null method list as nothing selected', () => {
    expect(
      draftFromSettings({
        enabled: true,
        campaignId: 'CAMPAIGN#c-1',
        allowedPaymentMethods: null,
        shareToken: null,
      } as never),
    ).toEqual({ enabled: true, campaignId: 'CAMPAIGN#c-1', methods: [], ackPayment: false, ackDisclosure: false });
  });
});

describe('buildMethodOptions', () => {
  it('offers the account methods plus Cash and Check', () => {
    expect(buildMethodOptions(['Venmo'])).toEqual(['Venmo', 'Cash', 'Check']);
  });

  it('does not duplicate a stored method that only differs by case', () => {
    expect(buildMethodOptions(['cash', 'Check'])).toEqual(['cash', 'Check']);
  });

  it('offers nothing beyond the globals when the account has no methods', () => {
    expect(buildMethodOptions([])).toEqual([...GLOBAL_PAYMENT_METHODS]);
  });
});

describe('acknowledgementIsBehind', () => {
  it('requires acceptance when nothing was ever recorded', () => {
    expect(acknowledgementIsBehind(null)).toBe(true);
    expect(acknowledgementIsBehind(undefined)).toBe(true);
  });

  it('requires acceptance again when the stored version is older', () => {
    expect(acknowledgementIsBehind(PUBLIC_ORDER_ACK_VERSION - 1)).toBe(true);
  });

  it('does not re-prompt while the stored version is current or newer', () => {
    expect(acknowledgementIsBehind(PUBLIC_ORDER_ACK_VERSION)).toBe(false);
    expect(acknowledgementIsBehind(PUBLIC_ORDER_ACK_VERSION + 1)).toBe(false);
  });
});

describe('acknowledgement copy', () => {
  it('carries exactly the two mandatory acknowledgements', () => {
    expect(PUBLIC_ORDER_ACKNOWLEDGEMENTS).toHaveLength(2);
    expect(PUBLIC_ORDER_ACKNOWLEDGEMENTS[0]).toContain('does not collect payment');
    expect(PUBLIC_ORDER_ACKNOWLEDGEMENTS[1]).toContain('QR image you uploaded');
  });

  it('states the campaign cap the settings copy uses', () => {
    expect(PUBLIC_ORDER_CAP).toBe(500);
  });
});
