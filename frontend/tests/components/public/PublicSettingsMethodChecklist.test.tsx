/**
 * Tests for PublicSettingsMethodChecklist.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PublicSettingsMethodChecklist } from '../../../src/components/public/PublicSettingsMethodChecklist';

const ALL_OPTIONS = ['Venmo', 'Zelle', 'Cash', 'Check'];

const renderChecklist = (
  overrides: Partial<Parameters<typeof PublicSettingsMethodChecklist>[0]> = {},
) => {
  const props = {
    availablePaymentMethods: ALL_OPTIONS,
    allowedPaymentMethods: [] as string[],
    onChange: vi.fn(),
    ...overrides,
  };
  render(<PublicSettingsMethodChecklist {...props} />);
  return props;
};

describe('PublicSettingsMethodChecklist', () => {
  it('lists the seller\'s real methods plus Cash and Check, not a hardcoded brand list', () => {
    renderChecklist();
    for (const name of ALL_OPTIONS) {
      expect(screen.getByRole('checkbox', { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole('checkbox', { name: 'Visa' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'MasterCard' })).not.toBeInTheDocument();
  });

  it('checks the methods present in the allowed list', () => {
    renderChecklist({ allowedPaymentMethods: ['Cash', 'Venmo'] });
    expect(screen.getByRole('checkbox', { name: 'Cash' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Venmo' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Check' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Zelle' })).not.toBeChecked();
  });

  it('matches the stored allowlist case-insensitively', () => {
    renderChecklist({ allowedPaymentMethods: ['venmo'] });
    expect(screen.getByRole('checkbox', { name: 'Venmo' })).toBeChecked();
  });

  it('adds a method when an unchecked box is clicked, preserving its canonical name', () => {
    const props = renderChecklist({ allowedPaymentMethods: ['Cash'] });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Zelle' }));
    expect(props.onChange).toHaveBeenCalledWith(['Cash', 'Zelle']);
  });

  it('removes a method and its case variants when a checked box is clicked', () => {
    const props = renderChecklist({ allowedPaymentMethods: ['Cash', 'venmo', 'Check'] });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Venmo' }));
    expect(props.onChange).toHaveBeenCalledWith(['Cash', 'Check']);
  });

  it('disables all checkboxes when disabled', () => {
    renderChecklist({ disabled: true });
    for (const name of ALL_OPTIONS) {
      expect(screen.getByRole('checkbox', { name })).toBeDisabled();
    }
  });
});
