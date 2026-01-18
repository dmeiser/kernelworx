/**
 * Tests for PaymentMethodCard component
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PaymentMethodCard } from '../src/components/PaymentMethodCard';

describe('PaymentMethodCard', () => {
  const mockOnEdit = vi.fn();
  const mockOnDelete = vi.fn();
  const mockOnUploadQR = vi.fn();
  const mockOnDeleteQR = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  const defaultProps = {
    method: { name: 'Venmo', qrCodeUrl: null },
    isReserved: false,
    onEdit: mockOnEdit,
    onDelete: mockOnDelete,
    onUploadQR: mockOnUploadQR,
    onDeleteQR: mockOnDeleteQR,
  };

  test('renders payment method name', () => {
    render(<PaymentMethodCard {...defaultProps} />);
    expect(screen.getByText('Venmo')).toBeInTheDocument();
  });

  test('shows Built-in chip for reserved methods', () => {
    render(<PaymentMethodCard {...defaultProps} isReserved={true} method={{ name: 'Cash', qrCodeUrl: null }} />);
    expect(screen.getByText('Built-in')).toBeInTheDocument();
  });

  test('does not show Built-in chip for custom methods', () => {
    render(<PaymentMethodCard {...defaultProps} />);
    expect(screen.queryByText('Built-in')).not.toBeInTheDocument();
  });

  test('shows QR code icon when method has QR code', () => {
    render(<PaymentMethodCard {...defaultProps} method={{ name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' }} />);
    expect(screen.getByLabelText('View QR code for Venmo')).toBeInTheDocument();
  });

  test('does not show QR code icon when method has no QR code', () => {
    render(<PaymentMethodCard {...defaultProps} />);
    expect(screen.queryByLabelText('View QR code for Venmo')).not.toBeInTheDocument();
  });

  test('opens QR preview dialog when QR icon clicked', async () => {
    const user = userEvent.setup();
    render(<PaymentMethodCard {...defaultProps} method={{ name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' }} />);

    await user.click(screen.getByLabelText('View QR code for Venmo'));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('QR Code for Venmo')).toBeInTheDocument();
    expect(screen.getByAltText('QR code for Venmo')).toBeInTheDocument();
  });

  test('closes QR preview dialog when Close clicked', async () => {
    const user = userEvent.setup();
    render(<PaymentMethodCard {...defaultProps} method={{ name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' }} />);

    await user.click(screen.getByLabelText('View QR code for Venmo'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  test('shows edit button for custom methods', () => {
    render(<PaymentMethodCard {...defaultProps} />);
    expect(screen.getByLabelText('Edit Venmo')).toBeInTheDocument();
  });

  test('hides edit button for reserved methods', () => {
    render(<PaymentMethodCard {...defaultProps} isReserved={true} method={{ name: 'Cash', qrCodeUrl: null }} />);
    expect(screen.queryByLabelText('Edit Cash')).not.toBeInTheDocument();
  });

  test('shows delete button for custom methods', () => {
    render(<PaymentMethodCard {...defaultProps} />);
    expect(screen.getByLabelText('Delete Venmo')).toBeInTheDocument();
  });

  test('hides delete button for reserved methods', () => {
    render(<PaymentMethodCard {...defaultProps} isReserved={true} method={{ name: 'Cash', qrCodeUrl: null }} />);
    expect(screen.queryByLabelText('Delete Cash')).not.toBeInTheDocument();
  });

  test('shows upload QR button when no QR code exists', () => {
    render(<PaymentMethodCard {...defaultProps} />);
    expect(screen.getByLabelText('Upload QR code for Venmo')).toBeInTheDocument();
  });

  test('hides upload QR button when QR code exists', () => {
    render(<PaymentMethodCard {...defaultProps} method={{ name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' }} />);
    expect(screen.queryByLabelText('Upload QR code for Venmo')).not.toBeInTheDocument();
  });

  test('shows delete QR button when QR code exists', () => {
    render(<PaymentMethodCard {...defaultProps} method={{ name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' }} />);
    expect(screen.getByLabelText('Delete QR code for Venmo')).toBeInTheDocument();
  });

  test('hides delete QR button when no QR code exists', () => {
    render(<PaymentMethodCard {...defaultProps} />);
    expect(screen.queryByLabelText('Delete QR code for Venmo')).not.toBeInTheDocument();
  });

  test('calls onEdit when edit button clicked', async () => {
    const user = userEvent.setup();
    render(<PaymentMethodCard {...defaultProps} />);

    await user.click(screen.getByLabelText('Edit Venmo'));
    expect(mockOnEdit).toHaveBeenCalledTimes(1);
  });

  test('calls onDelete when delete button clicked', async () => {
    const user = userEvent.setup();
    render(<PaymentMethodCard {...defaultProps} />);

    await user.click(screen.getByLabelText('Delete Venmo'));
    expect(mockOnDelete).toHaveBeenCalledTimes(1);
  });

  test('calls onUploadQR when upload QR button clicked', async () => {
    const user = userEvent.setup();
    render(<PaymentMethodCard {...defaultProps} />);

    await user.click(screen.getByLabelText('Upload QR code for Venmo'));
    expect(mockOnUploadQR).toHaveBeenCalledTimes(1);
  });

  test('calls onDeleteQR when delete QR button clicked', async () => {
    const user = userEvent.setup();
    render(<PaymentMethodCard {...defaultProps} method={{ name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' }} />);

    await user.click(screen.getByLabelText('Delete QR code for Venmo'));
    expect(mockOnDeleteQR).toHaveBeenCalledTimes(1);
  });

  test('disables delete button when isDeleting is true', () => {
    render(<PaymentMethodCard {...defaultProps} isDeleting={true} />);
    expect(screen.getByLabelText('Delete Venmo')).toBeDisabled();
  });

  test('disables delete QR button when isDeleting is true', () => {
    render(
      <PaymentMethodCard
        {...defaultProps}
        method={{ name: 'Venmo', qrCodeUrl: 'https://example.com/qr.png' }}
        isDeleting={true}
      />,
    );
    expect(screen.getByLabelText('Delete QR code for Venmo')).toBeDisabled();
  });

  test('hides all action buttons for reserved methods', () => {
    render(<PaymentMethodCard {...defaultProps} isReserved={true} method={{ name: 'Check', qrCodeUrl: null }} />);
    expect(screen.queryByLabelText(/Edit/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Delete/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Upload QR/)).not.toBeInTheDocument();
  });
});
