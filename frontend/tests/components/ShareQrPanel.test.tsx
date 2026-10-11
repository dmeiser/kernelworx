/**
 * Tests for the seller's share view: the URL, the copy affordance, the
 * client-generated QR, and the fullscreen mode used to hand a phone to a buyer.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ShareQrPanel } from '../../src/components/public/ShareQrPanel';

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn(() => Promise.resolve('data:image/png;base64,QRDATA')) },
}));

import QRCode from 'qrcode';

const SHARE_URL = 'https://dev.kernelworx.app/o/profile-id/share-token';

// The vi.mock factory above erases the signature, so re-state it for the
// per-test overrides.
const qrMock = vi.mocked(QRCode.toDataURL as unknown as (value: string, options?: unknown) => Promise<string>);

beforeEach(() => {
  qrMock.mockResolvedValue('data:image/png;base64,QRDATA');
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
});

describe('ShareQrPanel', () => {
  it('shows the share URL and a QR generated from it', async () => {
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    expect(screen.getByLabelText('Public order share URL')).toHaveValue(SHARE_URL);
    await waitFor(() => expect(screen.getAllByAltText('Public order share QR code').length).toBeGreaterThan(0));
    expect(QRCode.toDataURL).toHaveBeenCalledWith(SHARE_URL, expect.anything());
  });

  it('copies the URL and reports it', async () => {
    const onCopied = vi.fn();
    render(<ShareQrPanel shareUrl={SHARE_URL} onCopied={onCopied} />);
    await userEvent.click(screen.getByTestId('copy-share-url'));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(SHARE_URL));
    expect(onCopied).toHaveBeenCalled();
  });

  it('opens a fullscreen QR for handing the phone to a buyer', async () => {
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    await userEvent.click(screen.getByTestId('fullscreen-qr'));
    await waitFor(() => expect(screen.getByTestId('fullscreen-qr-dialog')).toBeInTheDocument());
  });

  it('renders the enlarged image inside the fullscreen dialog', async () => {
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    await waitFor(() => expect(screen.getByAltText('Public order share QR code')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('fullscreen-qr'));
    await waitFor(() => expect(screen.getByAltText('Public order share QR code, enlarged')).toBeInTheDocument());
  });

  it('keeps the URL field read-only', async () => {
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    const field = screen.getByLabelText('Public order share URL');
    // A direct change event proves the handler is a no-op, not just that the
    // browser refused the keystroke.
    fireEvent.change(field, { target: { value: 'tampered' } });
    expect(field).toHaveValue(SHARE_URL);
  });

  it('copies without a callback when the caller has none', async () => {
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    await userEvent.click(screen.getByTestId('copy-share-url'));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(SHARE_URL));
  });

  it('closes the fullscreen dialog again', async () => {
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    await waitFor(() => expect(screen.getByAltText('Public order share QR code')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('fullscreen-qr'));
    await waitFor(() => expect(screen.getByTestId('fullscreen-qr-dialog')).toBeInTheDocument());
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByTestId('fullscreen-qr-dialog')).not.toBeInTheDocument());
  });

  it('opens an empty fullscreen dialog when the QR could not be generated', async () => {
    qrMock.mockRejectedValueOnce(new Error('generation failed'));
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    await waitFor(() => expect(QRCode.toDataURL).toHaveBeenCalled());
    await userEvent.click(screen.getByTestId('fullscreen-qr'));
    await waitFor(() => expect(screen.getByTestId('fullscreen-qr-dialog')).toBeInTheDocument());
    expect(screen.queryByAltText('Public order share QR code, enlarged')).not.toBeInTheDocument();
  });

  it('ignores a QR that resolves after the panel unmounted', async () => {
    let resolveDataUrl: ((value: string) => void) | undefined;
    qrMock.mockImplementationOnce(
      (): Promise<string> => new Promise<string>((resolve) => { resolveDataUrl = resolve; }),
    );
    const view = render(<ShareQrPanel shareUrl={SHARE_URL} />);
    await waitFor(() => expect(QRCode.toDataURL).toHaveBeenCalled());
    view.unmount();
    resolveDataUrl?.('data:image/png;base64,LATE');
    await waitFor(() => expect(QRCode.toDataURL).toHaveBeenCalled());
  });

  it('renders no image when QR generation fails', async () => {
    qrMock.mockRejectedValueOnce(new Error('generation failed'));
    render(<ShareQrPanel shareUrl={SHARE_URL} />);
    await waitFor(() => expect(QRCode.toDataURL).toHaveBeenCalled());
    expect(screen.queryByAltText('Public order share QR code')).not.toBeInTheDocument();
  });
});
