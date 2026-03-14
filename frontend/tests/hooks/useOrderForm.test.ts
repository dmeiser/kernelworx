/**
 * Tests for useOrderForm hook
 */

import { describe, test, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useOrderForm } from '../../src/hooks/useOrderForm';

describe('useOrderForm', () => {
  test('initializes with default values', () => {
    const { result } = renderHook(() => useOrderForm());

    expect(result.current.customerName).toBe('');
    expect(result.current.customerPhone).toBe('');
    expect(result.current.street).toBe('');
    expect(result.current.city).toBe('');
    expect(result.current.state).toBe('');
    expect(result.current.zipCode).toBe('');
    expect(result.current.paymentMethod).toBe('');
    expect(result.current.notes).toBe('');
    expect(result.current.lineItems).toEqual([{ productId: '', quantity: 1 }]);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  test('setCustomerName updates customer name', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setCustomerName('John Doe'));
    expect(result.current.customerName).toBe('John Doe');
  });

  test('setCustomerPhone updates customer phone', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setCustomerPhone('555-1234'));
    expect(result.current.customerPhone).toBe('555-1234');
  });

  test('setStreet updates street', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setStreet('123 Main St'));
    expect(result.current.street).toBe('123 Main St');
  });

  test('setCity updates city', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setCity('Anytown'));
    expect(result.current.city).toBe('Anytown');
  });

  test('setState updates state', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setState('CA'));
    expect(result.current.state).toBe('CA');
  });

  test('setZipCode updates zip code', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setZipCode('90210'));
    expect(result.current.zipCode).toBe('90210');
  });

  test('setPaymentMethod updates payment method', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setPaymentMethod('Cash'));
    expect(result.current.paymentMethod).toBe('Cash');
  });

  test('setNotes updates notes', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setNotes('Deliver after 5pm'));
    expect(result.current.notes).toBe('Deliver after 5pm');
  });

  test('setLoading updates loading state', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setLoading(true));
    expect(result.current.loading).toBe(true);
    act(() => result.current.setLoading(false));
    expect(result.current.loading).toBe(false);
  });

  test('setError updates error state', () => {
    const { result } = renderHook(() => useOrderForm());
    act(() => result.current.setError('Something went wrong'));
    expect(result.current.error).toBe('Something went wrong');
    act(() => result.current.setError(null));
    expect(result.current.error).toBeNull();
  });

  describe('lineItems operations', () => {
    test('addLineItem appends a new empty line item', () => {
      const { result } = renderHook(() => useOrderForm());
      act(() => result.current.addLineItem());
      expect(result.current.lineItems).toHaveLength(2);
      expect(result.current.lineItems[1]).toEqual({ productId: '', quantity: 1 });
    });

    test('removeLineItem removes item at index', () => {
      const { result } = renderHook(() => useOrderForm());
      // Add two items, then remove first
      act(() => result.current.addLineItem());
      act(() => result.current.updateLineItem(0, 'productId', 'PROD~1'));
      act(() => result.current.updateLineItem(1, 'productId', 'PROD~2'));
      act(() => result.current.removeLineItem(0));
      expect(result.current.lineItems).toHaveLength(1);
      expect(result.current.lineItems[0].productId).toBe('PROD~2');
    });

    test('updateLineItem updates productId', () => {
      const { result } = renderHook(() => useOrderForm());
      act(() => result.current.updateLineItem(0, 'productId', 'PROD~1'));
      expect(result.current.lineItems[0].productId).toBe('PROD~1');
    });

    test('updateLineItem updates quantity with valid range', () => {
      const { result } = renderHook(() => useOrderForm());
      act(() => result.current.updateLineItem(0, 'quantity', '5'));
      expect(result.current.lineItems[0].quantity).toBe(5);
    });

    test('updateLineItem clamps quantity to minimum 1', () => {
      const { result } = renderHook(() => useOrderForm());
      act(() => result.current.updateLineItem(0, 'quantity', '0'));
      expect(result.current.lineItems[0].quantity).toBe(1);
    });

    test('updateLineItem clamps quantity to maximum 99999', () => {
      const { result } = renderHook(() => useOrderForm());
      act(() => result.current.updateLineItem(0, 'quantity', '100000'));
      expect(result.current.lineItems[0].quantity).toBe(99999);
    });

    test('updateLineItem defaults quantity to 1 on non-numeric input', () => {
      const { result } = renderHook(() => useOrderForm());
      act(() => result.current.updateLineItem(0, 'quantity', 'abc'));
      expect(result.current.lineItems[0].quantity).toBe(1);
    });
  });

  describe('loadFromOrder', () => {
    test('loads all fields from existing order', () => {
      const { result } = renderHook(() => useOrderForm());
      const order = {
        orderId: 'ORDER~123',
        customerName: 'Jane Smith',
        customerPhone: '555-9876',
        customerAddress: {
          street: '456 Oak Ave',
          city: 'Springfield',
          state: 'IL',
          zipCode: '62701',
        },
        paymentMethod: 'Venmo',
        notes: 'Ring doorbell',
        lineItems: [
          { productId: 'PROD~1', quantity: 3 },
          { productId: 'PROD~2', quantity: 1 },
        ],
      };

      act(() => result.current.loadFromOrder(order));

      expect(result.current.customerName).toBe('Jane Smith');
      expect(result.current.customerPhone).toBe('555-9876');
      expect(result.current.street).toBe('456 Oak Ave');
      expect(result.current.city).toBe('Springfield');
      expect(result.current.state).toBe('IL');
      expect(result.current.zipCode).toBe('62701');
      expect(result.current.paymentMethod).toBe('Venmo');
      expect(result.current.notes).toBe('Ring doorbell');
      expect(result.current.lineItems).toEqual([
        { productId: 'PROD~1', quantity: 3 },
        { productId: 'PROD~2', quantity: 1 },
      ]);
    });

    test('loads order with missing optional fields', () => {
      const { result } = renderHook(() => useOrderForm());
      const order = {
        orderId: 'ORDER~456',
        lineItems: [{ productId: 'PROD~1', quantity: 1 }],
      };

      act(() => result.current.loadFromOrder(order));

      expect(result.current.customerName).toBe('');
      expect(result.current.customerPhone).toBe('');
      expect(result.current.street).toBe('');
      expect(result.current.city).toBe('');
      expect(result.current.state).toBe('');
      expect(result.current.zipCode).toBe('');
      expect(result.current.paymentMethod).toBe('CASH');
      expect(result.current.notes).toBe('');
    });

    test('loads order with partial address', () => {
      const { result } = renderHook(() => useOrderForm());
      const order = {
        orderId: 'ORDER~789',
        customerAddress: { city: 'Portland' },
        lineItems: [{ productId: 'PROD~1', quantity: 1 }],
      };

      act(() => result.current.loadFromOrder(order));

      expect(result.current.street).toBe('');
      expect(result.current.city).toBe('Portland');
      expect(result.current.state).toBe('');
      expect(result.current.zipCode).toBe('');
    });
  });
});
