/**
 * Tests for PublicSettingsShareSection.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PublicSettingsShareSection } from '../../../src/components/public/PublicSettingsShareSection';

const { mockToDataURL } = vi.hoisted(() => ({
  mockToDataURL: vi.fn<(text: string, options?: unknown) => Promise<string>>(),
}));

vi.mock('qrcode', () => ({
  default: {
    toDataURL: mockToDataURL,
  },
}));

const CAMPAIGN_ID = 'CAMPAIGN#campaign-456';
const TOKEN = 'tok-1';
const QR_DATA_URL = 'data:image/png;base64,mockqrcode';
const expectedUrl = `${window.location.origin}/o/campaign-456/${TOKEN}`;

const renderSection = (shareToken: string | null = TOKEN) =>
  render(
    <PublicSettingsShareSection campaignId={CAMPAIGN_ID} shareToken={shareToken} campaignName="Spring Sale" />,
  );

describe('PublicSettingsShareSection', () => {
  beforeEach(() => {
    mockToDataURL.mockResolvedValue(QR_DATA_URL);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the absolute bare-id share URL and the QR code', async () => {
    renderSection();
    expect(screen.getByText('Share Link for Spring Sale')).toBeInTheDocument();
    expect(screen.getByTestId('share-url')).toHaveTextContent(expectedUrl);
    // The raw CAMPAIGN# prefix never enters the URL (a raw '#' truncates it).
    expect(screen.getByTestId('share-url').textContent).not.toContain('CAMPAIGN#');
    await waitFor(() => {
      expect(screen.getByTestId('share-qr')).toBeInTheDocument();
    });
    expect(mockToDataURL).toHaveBeenCalledWith(expectedUrl, { width: 400, margin: 2 });
    expect(screen.getByRole('img', { name: 'Share QR code for Spring Sale' })).toHaveAttribute(
      'src',
      QR_DATA_URL,
    );
  });

  it('explains the missing link when no token has been generated', () => {
    renderSection(null);
    expect(screen.getByText(/Share link not available/)).toBeInTheDocument();
    expect(screen.queryByTestId('share-url')).not.toBeInTheDocument();
    expect(mockToDataURL).not.toHaveBeenCalled();
  });

  it('omits the QR image when generation fails but keeps the link', async () => {
    mockToDataURL.mockRejectedValue(new Error('QR failed'));
    renderSection();
    expect(screen.getByTestId('share-url')).toHaveTextContent(expectedUrl);
    await waitFor(() => {
      expect(mockToDataURL).toHaveBeenCalled();
    });
    expect(screen.queryByTestId('share-qr')).not.toBeInTheDocument();
  });

  it('copies the link and shows confirmation', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    renderSection();
    await waitFor(() => {
      expect(screen.getByTestId('share-qr')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Copy Link' }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expectedUrl);
    });
    expect(screen.getByTestId('copy-copied')).toBeInTheDocument();
    expect(screen.queryByTestId('copy-failed')).not.toBeInTheDocument();
  });

  it('shows the manual-copy fallback when the clipboard write fails', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    renderSection();
    await waitFor(() => {
      expect(screen.getByTestId('share-qr')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Copy Link' }));
    await waitFor(() => {
      expect(screen.getByTestId('copy-failed')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('copy-copied')).not.toBeInTheDocument();
  });

  it('opens and closes the fullscreen QR dialog', async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByTestId('share-qr')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Fullscreen QR' }));
    await waitFor(() => {
      expect(screen.getByTestId('fullscreen-share-qr')).toBeInTheDocument();
    });
    expect(screen.getByText(/Hold this up for the buyer to scan/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => {
      expect(screen.queryByTestId('fullscreen-share-qr')).not.toBeInTheDocument();
    });
  });

  it('closes the fullscreen dialog via the backdrop', async () => {
    renderSection();
    await waitFor(() => {
      expect(screen.getByTestId('share-qr')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Fullscreen QR' }));
    await waitFor(() => {
      expect(screen.getByTestId('fullscreen-share-qr')).toBeInTheDocument();
    });
    fireEvent.click(document.querySelector('.MuiBackdrop-root') as Element);
    await waitFor(() => {
      expect(screen.queryByTestId('fullscreen-share-qr')).not.toBeInTheDocument();
    });
  });

  it('regenerates the QR when the share URL changes (rotate)', async () => {
    const { rerender } = renderSection();
    await waitFor(() => {
      expect(screen.getByTestId('share-qr')).toBeInTheDocument();
    });
    mockToDataURL.mockResolvedValue('data:image/png;base64,rotated');
    rerender(
      <PublicSettingsShareSection
        campaignId={CAMPAIGN_ID}
        shareToken="tok-2"
        campaignName="Spring Sale"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId('share-url')).toHaveTextContent(
        `${window.location.origin}/o/campaign-456/tok-2`,
      );
    });
    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'Share QR code for Spring Sale' })).toHaveAttribute(
        'src',
        'data:image/png;base64,rotated',
      );
    });
  });

  it('ignores a QR result that resolves after unmount', async () => {
    let resolveToDataURL: (value: string) => void = () => {};
    const pending = new Promise<string>((resolve) => {
      resolveToDataURL = resolve;
    });
    mockToDataURL.mockReturnValue(pending);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { unmount } = renderSection();
    await waitFor(() => {
      expect(mockToDataURL).toHaveBeenCalled();
    });
    unmount();
    resolveToDataURL('data:image/png;base64,late');
    await Promise.resolve();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('ignores a QR failure that rejects after unmount', async () => {
    let rejectToDataURL: (reason: unknown) => void = () => {};
    const pending = new Promise<string>((_resolve, reject) => {
      rejectToDataURL = reject;
    });
    mockToDataURL.mockReturnValue(pending);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { unmount } = renderSection();
    await waitFor(() => {
      expect(mockToDataURL).toHaveBeenCalled();
    });
    unmount();
    rejectToDataURL(new Error('late failure'));
    await Promise.resolve();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
