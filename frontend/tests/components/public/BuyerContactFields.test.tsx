/**
 * Tests for BuyerContactFields.
 *
 * The validation layer now produces per-address-field errors, but an error that
 * is never rendered is the same as no error at all: `errors.address` used to be
 * computed and then dropped on the floor. These cases pin that the aggregate
 * address error reaches the visible form and that each address box is marked
 * individually, so a buyer can tell which of the four the server would refuse.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BuyerContactFields } from '../../../src/components/public/BuyerContactFields';
import type {
  PublicOrderAddressForm,
  PublicOrderFieldErrors,
} from '../../../src/lib/publicOrderValidation';

const emptyAddress: PublicOrderAddressForm = { street: '', city: '', state: '', zipCode: '' };
const noErrors: PublicOrderFieldErrors = {};

/**
 * MUI appends a required marker to the label text of the two name fields, so
 * exact label matching misses them; a prefix match names the box unambiguously.
 * The label is escaped because one of them carries regex metacharacters.
 */
const field = (label: string) =>
  screen.getByLabelText(new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`));

const renderFields = (
  overrides: {
    address?: PublicOrderAddressForm;
    errors?: PublicOrderFieldErrors;
    phone?: string;
  } = {},
) => {
  const onFieldChange = vi.fn();
  const onAddressChange = vi.fn();
  render(
    <BuyerContactFields
      firstName="Ada"
      lastName="Lovelace"
      phone={overrides.phone ?? '555-123-4567'}
      email=""
      address={overrides.address ?? emptyAddress}
      errors={overrides.errors ?? noErrors}
      onFieldChange={onFieldChange}
      onAddressChange={onAddressChange}
    />,
  );
  return { onFieldChange, onAddressChange };
};

describe('BuyerContactFields', () => {
  it('renders the four address boxes', () => {
    renderFields();
    expect(field('Street address')).toBeInTheDocument();
    expect(field('City')).toBeInTheDocument();
    expect(field('State')).toBeInTheDocument();
    expect(field('ZIP code')).toBeInTheDocument();
  });

  it('reports address edits through the address change handler', () => {
    const { onAddressChange } = renderFields();
    fireEvent.change(field('Street address'), { target: { value: '1 Main St' } });
    fireEvent.change(field('City'), { target: { value: 'Springfield' } });
    fireEvent.change(field('State'), { target: { value: 'IL' } });
    fireEvent.change(field('ZIP code'), { target: { value: '62701' } });
    expect(onAddressChange).toHaveBeenCalledWith('street', '1 Main St');
    expect(onAddressChange).toHaveBeenCalledWith('city', 'Springfield');
    expect(onAddressChange).toHaveBeenCalledWith('state', 'IL');
    expect(onAddressChange).toHaveBeenCalledWith('zipCode', '62701');
  });

  it('reports name, phone, and email edits through the field change handler', () => {
    const { onFieldChange } = renderFields();
    fireEvent.change(field('First name'), { target: { value: 'Grace' } });
    fireEvent.change(field('Last name'), { target: { value: 'Hopper' } });
    fireEvent.change(field('Phone'), { target: { value: '555-000-1111' } });
    fireEvent.change(field('Email (optional)'), { target: { value: 'g@example.com' } });
    expect(onFieldChange).toHaveBeenCalledWith('firstName', 'Grace');
    expect(onFieldChange).toHaveBeenCalledWith('lastName', 'Hopper');
    expect(onFieldChange).toHaveBeenCalledWith('phone', '555-000-1111');
    expect(onFieldChange).toHaveBeenCalledWith('email', 'g@example.com');
  });
});

describe('BuyerContactFields error rendering', () => {
  it('renders the aggregate address error, which the form used to compute and drop', () => {
    renderFields({
      phone: '',
      address: { ...emptyAddress, street: '1 Main St' },
      errors: { address: 'Address is missing required fields: city, state, zipCode' },
    });
    expect(screen.getByText('Address is missing required fields: city, state, zipCode')).toBeInTheDocument();
  });

  it('marks each missing address box and leaves the filled one clean', () => {
    renderFields({
      phone: '',
      address: { street: '1 Main St', city: '', state: '', zipCode: '' },
      errors: {
        address: 'Address is missing required fields: city, state, zipCode',
        addressFields: {
          city: 'Required once an address is started.',
          state: 'Required once an address is started.',
          zipCode: 'Required once an address is started.',
        },
      },
    });
    for (const label of ['City', 'State', 'ZIP code']) {
      const input = field(label);
      expect(input).toHaveAttribute('aria-invalid', 'true');
      expect(input).toHaveAccessibleDescription('Required once an address is started.');
    }
    expect(field('Street address')).not.toHaveAttribute('aria-invalid', 'true');
  });

  it('prefers the field-level ZIP error over the helper text', () => {
    renderFields({
      phone: '',
      address: { street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '12' },
      errors: { address: 'ZIP code must be 5 or 9 digits', addressFields: { zipCode: 'ZIP code must be 5 or 9 digits' } },
    });
    expect(field('ZIP code')).toHaveAccessibleDescription('ZIP code must be 5 or 9 digits');
  });

  it('keeps the ZIP hint when there is no ZIP error', () => {
    renderFields();
    expect(field('ZIP code')).toHaveAccessibleDescription('5 or 9 digits.');
  });

  it('marks phone and email boxes with their own errors', () => {
    renderFields({
      phone: '555-1234',
      errors: { phone: 'Phone number must be a valid 10-digit US number', email: 'Email address is not valid' },
    });
    expect(field('Phone')).toHaveAccessibleDescription(
      'Phone number must be a valid 10-digit US number',
    );
    expect(field('Email (optional)')).toHaveAccessibleDescription('Email address is not valid');
  });

  it('shows the neutral helper text when nothing is wrong', () => {
    renderFields();
    expect(field('Phone')).toHaveAccessibleDescription(
      'A 10-digit US phone number. Phone or a complete address is required.',
    );
  });
});
