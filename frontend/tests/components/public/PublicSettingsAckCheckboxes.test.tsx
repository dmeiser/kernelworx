/**
 * Tests for PublicSettingsAckCheckboxes.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  PublicSettingsAckCheckboxes,
  PAYMENT_ACK_TEXT,
  DISCLOSURE_ACK_TEXT,
} from '../../../src/components/public/PublicSettingsAckCheckboxes';

const renderAcks = (overrides: Partial<Parameters<typeof PublicSettingsAckCheckboxes>[0]> = {}) => {
  const props = {
    paymentAckAccepted: false,
    disclosureAckAccepted: false,
    onPaymentAckChange: vi.fn(),
    onDisclosureAckChange: vi.fn(),
    ...overrides,
  };
  render(<PublicSettingsAckCheckboxes {...props} />);
  return props;
};

describe('PublicSettingsAckCheckboxes', () => {
  it('renders the two mandated acknowledgement texts (D4 and D5)', () => {
    renderAcks();
    expect(screen.getByText(PAYMENT_ACK_TEXT)).toBeInTheDocument();
    expect(screen.getByText(DISCLOSURE_ACK_TEXT)).toBeInTheDocument();
    expect(PAYMENT_ACK_TEXT).toContain('KernelWorx does not collect payment');
    expect(DISCLOSURE_ACK_TEXT).toContain('QR image');
  });

  it('reflects each accepted state independently', () => {
    renderAcks({ paymentAckAccepted: true, disclosureAckAccepted: false });
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();
  });

  it('forwards each checkbox change to its own handler', () => {
    const props = renderAcks();
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);
    expect(props.onPaymentAckChange).toHaveBeenCalledWith(true);
    expect(props.onDisclosureAckChange).not.toHaveBeenCalled();
    fireEvent.click(checkboxes[1]);
    expect(props.onDisclosureAckChange).toHaveBeenCalledWith(true);
  });

  it('disables both checkboxes when disabled', () => {
    renderAcks({ disabled: true });
    for (const checkbox of screen.getAllByRole('checkbox')) {
      expect(checkbox).toBeDisabled();
    }
  });
});
