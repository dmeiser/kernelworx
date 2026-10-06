/**
 * Tests for the payment method QR block.
 *
 * The attribute assertions are the point: `crossOrigin="anonymous"` is what
 * makes the canvas decode possible at all, `referrerPolicy="no-referrer"` keeps
 * the capability-bearing page URL out of S3 access logs, and
 * `rel="noopener noreferrer"` keeps it out of the payment site's Referer when
 * the decoded link is clicked.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PaymentMethodChoice, QR_NO_LINK_HINT } from '../../src/components/public/PaymentMethodChoice';

vi.mock('../../src/lib/qrDecode', () => ({
  decodeQrLink: vi.fn(() => null),
}));

import { decodeQrLink } from '../../src/lib/qrDecode';

const method = { name: 'Venmo', qrCodeUrl: 'https://bucket.s3.amazonaws.com/qr.png?X-Amz-Signature=x' };

beforeEach(() => {
  vi.mocked(decodeQrLink).mockReturnValue(null);
});

const getImage = () => screen.getByRole('img', { name: 'Payment QR code for Venmo' });

describe('PaymentMethodChoice', () => {
  it('renders the method name as a selectable radio', () => {
    render(<PaymentMethodChoice method={method} selected={false} onSelect={vi.fn()} />);
    expect(screen.getByText('Venmo')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('selects the method when the radio changes', async () => {
    const onSelect = vi.fn();
    render(<PaymentMethodChoice method={method} selected={false} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('radio'));
    expect(onSelect).toHaveBeenCalledWith('Venmo');
  });

  it('selects the method when the label is clicked', async () => {
    const onSelect = vi.fn();
    render(<PaymentMethodChoice method={method} selected={false} onSelect={onSelect} />);
    await userEvent.click(screen.getByTestId('payment-label-Venmo'));
    expect(onSelect).toHaveBeenCalledWith('Venmo');
  });

  it('selects the method from the keyboard on the label', () => {
    const onSelect = vi.fn();
    render(<PaymentMethodChoice method={method} selected={false} onSelect={onSelect} />);
    const label = screen.getByTestId('payment-label-Venmo');
    fireEvent.keyDown(label, { key: 'Enter' });
    fireEvent.keyDown(label, { key: ' ' });
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(onSelect).toHaveBeenLastCalledWith('Venmo');
  });

  it('ignores other keys on the label', () => {
    const onSelect = vi.fn();
    render(<PaymentMethodChoice method={method} selected={false} onSelect={onSelect} />);
    fireEvent.keyDown(screen.getByTestId('payment-label-Venmo'), { key: 'a' });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('loads the QR image anonymously and without a referrer', () => {
    render(<PaymentMethodChoice method={method} selected onSelect={vi.fn()} />);
    const image = getImage();
    expect(image).toHaveAttribute('crossOrigin', 'anonymous');
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('shows the scan-from-another-device hint when nothing decodes', async () => {
    render(<PaymentMethodChoice method={method} selected onSelect={vi.fn()} />);
    fireEvent.load(getImage());
    expect(await screen.findByTestId('qr-no-link-hint')).toHaveTextContent(QR_NO_LINK_HINT);
    expect(screen.queryByTestId('decoded-payment-link')).not.toBeInTheDocument();
  });

  it('renders a decoded link with rel="noopener noreferrer"', async () => {
    vi.mocked(decodeQrLink).mockReturnValue('https://pay.example.com/invoice');
    render(<PaymentMethodChoice method={method} selected onSelect={vi.fn()} />);
    fireEvent.load(getImage());

    const link = await screen.findByTestId('decoded-payment-link');
    expect(link).toHaveAttribute('href', 'https://pay.example.com/invoice');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('never renders a link the allowlist rejected', async () => {
    vi.mocked(decodeQrLink).mockReturnValue(null);
    render(<PaymentMethodChoice method={method} selected onSelect={vi.fn()} />);
    fireEvent.load(getImage());
    expect(await screen.findByTestId('qr-no-link-hint')).toBeInTheDocument();
  });

  it('reports a failed image load so the offer can be refreshed', () => {
    const onQrExpired = vi.fn();
    render(<PaymentMethodChoice method={method} selected onSelect={vi.fn()} onQrExpired={onQrExpired} />);
    fireEvent.error(getImage());
    expect(onQrExpired).toHaveBeenCalled();
  });

  it('handles image load when ref is null or element is missing', () => {
    const { unmount } = render(<PaymentMethodChoice method={method} selected onSelect={vi.fn()} />);
    const img = getImage();
    unmount();
    // firing load after unmount exercises element === null branch
    fireEvent.load(img);
  });

  it('renders a decoded mailto: link', async () => {
    vi.mocked(decodeQrLink).mockReturnValue('mailto:scout@example.com?subject=order');
    render(<PaymentMethodChoice method={method} selected onSelect={vi.fn()} />);
    fireEvent.load(getImage());

    const link = await screen.findByTestId('decoded-payment-link');
    expect(link).toHaveAttribute('href', 'mailto:scout@example.com?subject=order');
    expect(link).toHaveTextContent('mailto:scout@example.com?subject=order');
  });
});
