/**
 * Tests for usePublicOrderForm.
 *
 * Four behaviours are pinned here, all of them about what the buyer's taps
 * actually do:
 *  - a typed quantity is clamped to the picker's range, and the on-screen
 *    estimate is built from exactly the items the submit path will send, so the
 *    two can never disagree (a negative used to subtract from the total while
 *    the submit path silently dropped the line);
 *  - `submitNow` refuses to re-enter, because v1 has no idempotency key and a
 *    double-tap is two orders burning two slots of the campaign's cap;
 *  - a stale `submitError` from a failed attempt is cleared before a new one,
 *    so a corrected form is not shown the old failure;
 *  - `submit()` validates the form once and reads the result, rather than
 *    validating twice and letting the two answers diverge.
 *
 * The error text is asserted through the real public-checkout mapper, so these
 * also pin that an anonymous buyer never sees a raw DynamoDB fault.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { usePublicOrderForm } from '../../src/hooks/usePublicOrderForm';
import { MAX_PUBLIC_QUANTITY, validatePublicOrderForm } from '../../src/lib/publicOrderValidation';
import type { PublicOfferView } from '../../src/components/public/publicOrderTypes';
import type { GqlPublicCreateOrderMutation } from '../../src/types/graphql-generated';

const { useMutationMock } = vi.hoisted(() => ({ useMutationMock: vi.fn() }));

vi.mock('@apollo/client/react', () => ({ useMutation: useMutationMock }));

vi.mock('../../src/lib/publicOrderValidation', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/lib/publicOrderValidation')>();
  return { ...actual, validatePublicOrderForm: vi.fn(actual.validatePublicOrderForm) };
});

const mockedValidate = vi.mocked(validatePublicOrderForm);

const offer: PublicOfferView = {
  sellerName: 'Acme Troop',
  campaignId: 'CAMPAIGN#c1',
  campaignName: 'Spring Sale',
  products: [
    { productId: 'PROD#1', productName: 'Cookie Box', price: 10 },
    { productId: 'PROD#2', productName: 'Magazine', price: 4 },
  ],
  paymentMethods: [{ name: 'Venmo', qrCodeUrl: null }],
};

/** A deferred promise, so a mutation can be held in flight while a second tap lands. */
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const successPayload = (overrides: Partial<GqlPublicCreateOrderMutation['publicCreateOrder']> = {}) => ({
  data: {
    publicCreateOrder: {
      orderId: 'ORDER#c1#abc',
      receiptUrl: '/r/c1/abc',
      totalAmount: 24,
      buyerEmailProvided: true,
      confirmationEmailSent: true,
      ...overrides,
    },
  },
});

/** An Apollo mutation error shaped the way the public client reports one. */
const gqlFailure = (message: string, code?: string) => ({
  graphQLErrors: [code === undefined ? { message } : { message, extensions: { code } }],
  networkError: undefined,
});

/** A failure where the request never reached the server at all. */
const networkFailure = () => ({
  graphQLErrors: [],
  networkError: new Error('Network request failed'),
});

/** Fills in a form the validator accepts, so submit() reaches the mutation. */
const fillValidForm = (hook: { current: ReturnType<typeof usePublicOrderForm> }, { email = 'ada@example.com' } = {}) => {
  act(() => hook.current.setField('firstName', 'Ada'));
  act(() => hook.current.setField('lastName', 'Lovelace'));
  act(() => hook.current.setField('phone', '5551234567'));
  if (email) {
    act(() => hook.current.setField('email', email));
  }
  act(() => hook.current.setField('paymentMethod', 'Venmo'));
  act(() => hook.current.setQuantity('PROD#1', 2));
};

const renderFormHook = (mutate = vi.fn().mockResolvedValue(successPayload())) => {
  useMutationMock.mockReturnValue([mutate]);
  return { mutate, hook: renderHook(() => usePublicOrderForm({ offer, token: 'tok-1' })).result };
};

describe('usePublicOrderForm quantity clamping', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('clamps a negative quantity to zero', () => {
    const { hook } = renderFormHook();
    act(() => hook.current.setQuantity('PROD#1', -5));
    expect(hook.current.form.lineItems['PROD#1']).toBe(0);
  });

  it('updates one address field without touching the rest of the form', () => {
    const { hook } = renderFormHook();
    act(() => hook.current.setField('firstName', 'Ada'));
    act(() => hook.current.setAddressField('city', 'Springfield'));
    expect(hook.current.form.address.city).toBe('Springfield');
    expect(hook.current.form.address.state).toBe('');
    expect(hook.current.form.firstName).toBe('Ada');
  });

  it('clamps a quantity above the picker maximum', () => {
    const { hook } = renderFormHook();
    act(() => hook.current.setQuantity('PROD#1', MAX_PUBLIC_QUANTITY + 50));
    expect(hook.current.form.lineItems['PROD#1']).toBe(MAX_PUBLIC_QUANTITY);
  });

  it('truncates a fraction and turns a non-number into zero', () => {
    const { hook } = renderFormHook();
    act(() => hook.current.setQuantity('PROD#1', 2.9));
    act(() => hook.current.setQuantity('PROD#2', Number.NaN));
    expect(hook.current.form.lineItems['PROD#1']).toBe(2);
    expect(hook.current.form.lineItems['PROD#2']).toBe(0);
  });

  it('excludes an out-of-range quantity from the estimate rather than subtracting from it', () => {
    const { hook } = renderFormHook();
    act(() => hook.current.setQuantity('PROD#1', 1));
    expect(hook.current.totalAmount).toBe(10);
    act(() => hook.current.setQuantity('PROD#1', -3));
    expect(hook.current.totalAmount).toBe(0);
  });

  it('estimates from the offer prices of the submitted items only', () => {
    const { hook } = renderFormHook();
    act(() => hook.current.setQuantity('PROD#1', 2));
    act(() => hook.current.setQuantity('PROD#2', 1));
    act(() => hook.current.setQuantity('PROD#GONE', 5));
    expect(hook.current.totalAmount).toBe(24);
  });
});

describe('usePublicOrderForm submit re-entry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('sends one mutation for two taps that land before the first resolves', async () => {
    const gate = deferred<ReturnType<typeof successPayload>>();
    const mutate = vi.fn().mockReturnValue(gate.promise);
    const { hook } = renderFormHook(mutate);
    fillValidForm(hook);

    await act(async () => {
      void hook.current.submitNow();
      void hook.current.submitNow();
      gate.resolve(successPayload());
      await gate.promise;
    });

    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it('reports submitting while the mutation is in flight and clears it afterwards', async () => {
    const gate = deferred<ReturnType<typeof successPayload>>();
    const mutate = vi.fn().mockReturnValue(gate.promise);
    const { hook } = renderFormHook(mutate);

    let pending: Promise<void>;
    act(() => {
      pending = hook.current.submitNow();
    });
    expect(hook.current.submitting).toBe(true);

    await act(async () => {
      gate.resolve(successPayload());
      await pending!;
    });
    expect(hook.current.submitting).toBe(false);
  });

  it('allows a fresh attempt once the previous one settled', async () => {
    const { hook, mutate } = renderFormHook();
    await act(async () => {
      await hook.current.submitNow();
    });
    await act(async () => {
      await hook.current.submitNow();
    });
    expect(mutate).toHaveBeenCalledTimes(2);
  });
});

describe('usePublicOrderForm stale submit errors', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('clears the previous attempt error before starting a new one', async () => {
    const mutate = vi
      .fn()
      .mockRejectedValueOnce(gqlFailure('boom', 'INTERNAL_ERROR'))
      .mockResolvedValue(successPayload());
    const { hook } = renderFormHook(mutate);

    await act(async () => {
      await hook.current.submitNow();
    });
    const firstError = hook.current.submitError;
    expect(firstError).toBeTruthy();

    let pending: Promise<void>;
    act(() => {
      pending = hook.current.submitNow();
    });
    // Read before the second attempt settles: the old message must already be gone.
    expect(hook.current.submitError).toBeNull();
    await act(async () => {
      await pending!;
    });
    expect(hook.current.submitError).toBeNull();
  });

  it('keeps the first error visible after a failed attempt', async () => {
    const { hook } = renderFormHook(vi.fn().mockRejectedValue(gqlFailure('boom', 'NOPE')));
    await act(async () => {
      await hook.current.submitNow();
    });
    expect(hook.current.submitError).toBeTruthy();
  });
});

describe('usePublicOrderForm anonymous error mapping', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('never surfaces a raw DynamoDB fault to the buyer', async () => {
    const { hook } = renderFormHook(
      vi.fn().mockRejectedValue(
        gqlFailure(
          'One or more parameter values were invalid: Cannot do a put on an item with a table that has a DynamoDB stream. Request id: ABC123 https://console.aws.amazon.com/dynamodb/',
          'InternalServerError',
        ),
      ),
    );
    await act(async () => {
      await hook.current.submitNow();
    });
    const shown = hook.current.submitError ?? '';
    expect(shown).toMatch(/something went wrong/i);
    expect(shown).not.toMatch(/dynamodb|aws.amazon|request id/i);
  });

  it('preserves the backend INVALID_INPUT wording so the buyer can act on it', async () => {
    const { hook } = renderFormHook(
      vi.fn().mockRejectedValue(gqlFailure('Address is missing required fields: city, state, zipCode', 'INVALID_INPUT')),
    );
    await act(async () => {
      await hook.current.submitNow();
    });
    expect(hook.current.submitError).toBe('Address is missing required fields: city, state, zipCode');
  });

  it('names a dead link without leaking internals', async () => {
    const { hook } = renderFormHook(vi.fn().mockRejectedValue(gqlFailure('order not found', 'NOT_FOUND')));
    await act(async () => {
      await hook.current.submitNow();
    });
    expect(hook.current.submitError).toBe('This order link is no longer available.');
  });

  it('names the campaign cap separately from a broken link', async () => {
    const { hook } = renderFormHook(
      vi.fn().mockRejectedValue(gqlFailure('cap', 'PUBLIC_ORDER_LIMIT_EXCEEDED')),
    );
    await act(async () => {
      await hook.current.submitNow();
    });
    expect(hook.current.submitError).toBe('This campaign has reached its public order limit.');
  });

  it('blames the connection when the request never got an answer', async () => {
    const { hook } = renderFormHook(vi.fn().mockRejectedValue(networkFailure()));
    await act(async () => {
      await hook.current.submitNow();
    });
    expect(hook.current.submitError).toMatch(/could not reach the server/i);
  });
});

describe('usePublicOrderForm submit validation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('validates the form once per submit', async () => {
    const { hook, mutate } = renderFormHook();
    fillValidForm(hook);
    await act(async () => {
      await hook.current.submit();
    });
    expect(mockedValidate).toHaveBeenCalledTimes(1);
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it('does not reach the network when validation fails', async () => {
    const { hook, mutate } = renderFormHook();
    await act(async () => {
      await hook.current.submit();
    });
    expect(mutate).not.toHaveBeenCalled();
    expect(hook.current.errors.firstName).toBe('First name is required');
  });

  it('prompts for an email instead of submitting when none was given', async () => {
    const { hook, mutate } = renderFormHook();
    fillValidForm(hook, { email: '' });
    await act(async () => {
      await hook.current.submit();
    });
    expect(mutate).not.toHaveBeenCalled();
    expect(hook.current.noEmailPrompt).toBe(true);
  });

  it('records the field errors the form state produced', async () => {
    const { hook } = renderFormHook();
    act(() => hook.current.setField('firstName', 'Ada'));
    act(() => hook.current.setField('lastName', 'Lovelace'));
    act(() => hook.current.setField('paymentMethod', 'Venmo'));
    act(() => hook.current.setQuantity('PROD#1', 1));
    act(() => hook.current.setField('phone', '12345'));
    await act(async () => {
      await hook.current.submit();
    });
    expect(hook.current.errors.phone).toBe('Phone number must be a valid 10-digit US number');
  });
});

describe('usePublicOrderForm success state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('records the receipt and the summary built from the form and offer', async () => {
    const { hook } = renderFormHook();
    fillValidForm(hook);
    await act(async () => {
      await hook.current.submit();
    });
    await waitFor(() => expect(hook.current.receipt).not.toBeNull());
    expect(hook.current.receipt?.orderId).toBe('ORDER#c1#abc');
    expect(hook.current.summary?.lineItems).toEqual([
      { productId: 'PROD#1', productName: 'Cookie Box', quantity: 2, pricePerUnit: 10, subtotal: 20 },
    ]);
    expect(hook.current.summary?.paymentMethod).toBe('Venmo');
  });

  it('prefers the payment method the create response echoes', async () => {
    const mutate = vi
      .fn()
      .mockResolvedValue({ ...successPayload(), data: { publicCreateOrder: { ...successPayload().data.publicCreateOrder, paymentMethodName: 'Check' } } });
    const { hook } = renderFormHook(mutate);
    fillValidForm(hook);
    await act(async () => {
      await hook.current.submitNow();
    });
    expect(hook.current.summary?.paymentMethod).toBe('Check');
  });

  it('sends the campaign id and token from the offer, not a profile id', async () => {
    const { hook, mutate } = renderFormHook();
    fillValidForm(hook);
    await act(async () => {
      await hook.current.submitNow();
    });
    const sent = mutate.mock.calls[0][0] as { variables: { input: Record<string, unknown> } };
    expect(sent.variables.input.campaignId).toBe('CAMPAIGN#c1');
    expect(sent.variables.input.token).toBe('tok-1');
    expect(sent.variables.input).not.toHaveProperty('profileId');
  });
});
