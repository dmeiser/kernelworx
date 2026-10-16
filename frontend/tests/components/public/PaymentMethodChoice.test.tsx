/**
 * Tests for PaymentMethodChoice.
 *
 * Covers the QR image security plumbing (crossOrigin/referrerPolicy), the
 * decoded-link render path (scheme allowlist + rel="noopener noreferrer"),
 * and the expired-QR re-fetch hook.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PaymentMethodChoice, QR_NO_LINK_HINT } from '../../../src/components/public/PaymentMethodChoice';
import type { PublicPaymentMethodView } from '../../../src/components/public/publicOrderTypes';
import { decodeQrLink } from '../../../src/lib/qrDecode';

vi.mock('../../../src/lib/qrDecode', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../src/lib/qrDecode')>();
  return {
    ...actual,
    decodeQrLink: vi.fn(),
  };
});

const mockedDecodeQrLink = vi.mocked(decodeQrLink);

const qrMethod: PublicPaymentMethodView = {
  name: 'Venmo',
  qrCodeUrl: 'https://exports.example/qr.png',
};

const cashMethod: PublicPaymentMethodView = { name: 'Cash', qrCodeUrl: null };

describe('PaymentMethodChoice', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedDecodeQrLink.mockReturnValue(null);
  });

  it('selects the method when the label is clicked', () => {
    const onSelect = vi.fn();
    render(<PaymentMethodChoice method={cashMethod} selected={false} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId('payment-label-Cash'));
    expect(onSelect).toHaveBeenCalledWith('Cash');
  });

  it('selects the method from the label keyboard handler', () => {
    const onSelect = vi.fn();
    render(<PaymentMethodChoice method={cashMethod} selected={false} onSelect={onSelect} />);
    const label = screen.getByTestId('payment-label-Cash');
    fireEvent.keyDown(label, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith('Cash');
    fireEvent.keyDown(label, { key: ' ' });
    expect(onSelect).toHaveBeenCalledWith('Cash');
    fireEvent.keyDown(label, { key: 'Tab' });
    expect(onSelect).toHaveBeenCalledTimes(2);
  });

  it('shows the no-QR notice for a selected method without a QR image', () => {
    render(<PaymentMethodChoice method={cashMethod} selected onSelect={vi.fn()} />);
    expect(screen.getByTestId('payment-no-qr')).toBeInTheDocument();
  });

  it('renders nothing extra when not selected', () => {
    render(<PaymentMethodChoice method={qrMethod} selected={false} onSelect={vi.fn()} />);
    expect(screen.queryByAltText('Payment QR code for Venmo')).not.toBeInTheDocument();
  });

  it('renders the QR image with the security attributes and decodes on load', () => {
    mockedDecodeQrLink.mockReturnValue('https://venmo.com/u/seller');
    render(<PaymentMethodChoice method={qrMethod} selected onSelect={vi.fn()} />);
    const image = screen.getByAltText('Payment QR code for Venmo');
    expect(image).toHaveAttribute('crossorigin', 'anonymous');
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer');
    fireEvent.load(image);
    const link = screen.getByTestId('decoded-payment-link');
    expect(link).toHaveAttribute('href', 'https://venmo.com/u/seller');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('shows the scan hint when decoding finds no link', () => {
    render(<PaymentMethodChoice method={qrMethod} selected onSelect={vi.fn()} />);
    fireEvent.load(screen.getByAltText('Payment QR code for Venmo'));
    expect(screen.getByTestId('qr-no-link-hint')).toHaveTextContent(QR_NO_LINK_HINT);
    expect(screen.queryByTestId('decoded-payment-link')).not.toBeInTheDocument();
  });

  it('drops a decoded link whose scheme is not allowlisted', () => {
    mockedDecodeQrLink.mockReturnValue('http://evil.example/cap');
    render(<PaymentMethodChoice method={qrMethod} selected onSelect={vi.fn()} />);
    fireEvent.load(screen.getByAltText('Payment QR code for Venmo'));
    expect(screen.getByTestId('qr-no-link-hint')).toBeInTheDocument();
    expect(screen.queryByTestId('decoded-payment-link')).not.toBeInTheDocument();
  });

  it('notifies when the QR image fails to load (expired pre-signed URL)', () => {
    const onQrExpired = vi.fn();
    render(<PaymentMethodChoice method={qrMethod} selected onSelect={vi.fn()} onQrExpired={onQrExpired} />);
    fireEvent.error(screen.getByAltText('Payment QR code for Venmo'));
    expect(onQrExpired).toHaveBeenCalledTimes(1);
  });
});
