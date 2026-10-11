/**
 * Tests for the public order form hook.
 *
 * The page tests cover the happy paths; these pin the hook's own edges: the
 * running total ignores a quantity whose product is no longer in the offer (a
 * seller can edit the catalog while the buyer's page sits open), and the
 * no-email prompt is raised instead of submitting when the buyer left the
 * optional address blank.
 */

import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import type { ReactNode } from 'react';
import { usePublicOrderForm } from '../../src/hooks/usePublicOrderForm';
import type { PublicOfferView } from '../../src/components/public/publicOrderTypes';

const offer: PublicOfferView = {
  sellerName: 'Troop 42 Popcorn',
  campaignId: 'campaign-1',
  campaignName: 'Fall popcorn sale',
  products: [{ productId: 'p-1', productName: 'Large bag', price: 12.5, description: null }],
  paymentMethods: [{ name: 'Cash', qrCodeUrl: null }],
};

const wrapper = ({ children }: { children: ReactNode }) => <MockedProvider mocks={[]} children={children} />;

function renderForm() {
  return renderHook(() => usePublicOrderForm({ profileId: 'p-1', token: 't', offer }), { wrapper });
}

describe('usePublicOrderForm', () => {
  it('starts with an empty form and no errors', () => {
    const { result } = renderForm();
    expect(result.current.form.firstName).toBe('');
    expect(result.current.errors).toEqual({});
    expect(result.current.totalAmount).toBe(0);
  });

  it('totals the quantities the buyer set', () => {
    const { result } = renderForm();
    act(() => result.current.setQuantity('p-1', 2));
    expect(result.current.totalAmount).toBe(25);
  });

  it('ignores a quantity for a product the offer no longer lists', () => {
    const { result } = renderForm();
    act(() => result.current.setQuantity('gone-product', 3));
    expect(result.current.totalAmount).toBe(0);
  });

  it('writes through field and address edits', () => {
    const { result } = renderForm();
    act(() => result.current.setField('firstName', 'Ada'));
    act(() => result.current.setAddressField('city', 'Anytown'));
    expect(result.current.form.firstName).toBe('Ada');
    expect(result.current.form.address.city).toBe('Anytown');
  });

  it('asks before submitting when no email was given', async () => {
    const { result } = renderForm();
    act(() => {
      result.current.setField('firstName', 'Ada');
      result.current.setField('lastName', 'Lovelace');
      result.current.setField('phone', '5558675309');
      result.current.setField('paymentMethod', 'Cash');
      result.current.setQuantity('p-1', 1);
    });
    await act(async () => {
      await result.current.submit();
    });
    expect(result.current.noEmailPrompt).toBe(true);
    expect(result.current.receipt).toBeNull();
  });

  it('reports validation errors instead of prompting when the form is incomplete', async () => {
    const { result } = renderForm();
    await act(async () => {
      await result.current.submit();
    });
    expect(result.current.noEmailPrompt).toBe(false);
    expect(result.current.errors.firstName).toBeTruthy();
  });
});
