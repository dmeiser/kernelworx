/**
 * Tests for QrCodeImage component
 */

import { describe, test, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QrCodeImage } from '../src/components/QrCodeImage';

describe('QrCodeImage', () => {
  test('shows fallback message when qrCodeUrl is null', () => {
    render(<QrCodeImage qrCodeUrl={null} methodName="Venmo" />);
    expect(screen.getByText(/No QR code available/i)).toBeInTheDocument();
  });

  test('renders QR code image when url is provided', () => {
    render(<QrCodeImage qrCodeUrl="https://example.com/qr.png" methodName="Venmo" />);
    const img = screen.getByRole('img', { name: /QR code for Venmo/i });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', 'https://example.com/qr.png');
  });

  test('uses custom maxHeight', () => {
    render(<QrCodeImage qrCodeUrl="https://example.com/qr.png" methodName="PayPal" maxHeight={200} />);
    const img = screen.getByRole('img', { name: /QR code for PayPal/i });
    expect(img).toBeInTheDocument();
  });
});
