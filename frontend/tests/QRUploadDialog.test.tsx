/**
 * Tests for QRUploadDialog component
 */

import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, test, expect, vi, beforeEach } from 'vitest';
import { QRUploadDialog } from '../src/components/QRUploadDialog';

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  onUpload: vi.fn().mockResolvedValue(undefined),
  methodName: 'Venmo',
  isLoading: false,
};

// Helper to create mock files
const createMockFile = (name: string, size: number, type: string): File => {
  const buffer = new ArrayBuffer(size);
  return new File([buffer], name, { type });
};

describe('QRUploadDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock URL.createObjectURL and revokeObjectURL
    global.URL.createObjectURL = vi.fn(() => 'blob:mock-url');
    global.URL.revokeObjectURL = vi.fn();
  });

  describe('rendering', () => {
    test('renders dialog when open', () => {
      render(<QRUploadDialog {...defaultProps} />);

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByText(/Upload QR Code for Venmo/)).toBeInTheDocument();
    });

    test('does not render dialog when closed', () => {
      render(<QRUploadDialog {...defaultProps} open={false} />);

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    test('renders upload area with instructions', () => {
      render(<QRUploadDialog {...defaultProps} />);

      expect(screen.getByText(/Click to select an image/i)).toBeInTheDocument();
      expect(screen.getByText(/PNG, JPG, or WEBP \(max 5MB\)/i)).toBeInTheDocument();
    });

    test('renders upload and cancel buttons', () => {
      render(<QRUploadDialog {...defaultProps} />);

      expect(screen.getByRole('button', { name: /upload/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    });
  });

  describe('file selection', () => {
    test('disables Upload button when no file selected', () => {
      render(<QRUploadDialog {...defaultProps} />);

      expect(screen.getByRole('button', { name: /upload/i })).toBeDisabled();
    });

    test('shows preview when valid file is selected', async () => {
      const user = userEvent.setup();
      render(<QRUploadDialog {...defaultProps} />);

      const file = createMockFile('qr-code.png', 1024 * 100, 'image/png');
      const input = screen.getByLabelText('Select QR code image');

      await user.upload(input, file);

      await waitFor(() => {
        expect(screen.getByAltText('QR code preview')).toBeInTheDocument();
      });
    });

    test('enables Upload button when valid file is selected', async () => {
      const user = userEvent.setup();
      render(<QRUploadDialog {...defaultProps} />);

      const file = createMockFile('qr-code.png', 1024 * 100, 'image/png');
      const input = screen.getByLabelText('Select QR code image');

      await user.upload(input, file);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /upload/i })).toBeEnabled();
      });
    });
  });

  describe('file validation', () => {
    // Note: jsdom's file input doesn't filter by accept attribute, so we test the validateFile function behavior
    // by checking the file size validation which uses the same error display mechanism
    test('shows error for file exceeding 5MB', async () => {
      const user = userEvent.setup();
      render(<QRUploadDialog {...defaultProps} />);

      // 6MB file
      const file = createMockFile('large-image.png', 6 * 1024 * 1024, 'image/png');
      const input = screen.getByLabelText('Select QR code image');

      await user.upload(input, file);

      await waitFor(() => {
        expect(screen.getByText(/File is too large/i)).toBeInTheDocument();
        expect(screen.getByText(/Maximum size is 5MB/i)).toBeInTheDocument();
      });
    });

    test('shows error for unsupported file type', () => {
      render(<QRUploadDialog {...defaultProps} />);

      const file = createMockFile('document.pdf', 1024 * 100, 'application/pdf');
      const input = screen.getByLabelText('Select QR code image') as HTMLInputElement;

      // Use fireEvent + Object.defineProperty to bypass userEvent accept-filter
      Object.defineProperty(input, 'files', { value: [file], configurable: true });
      fireEvent.change(input);

      expect(screen.getByText(/Please select a PNG, JPG, or WEBP image file/i)).toBeInTheDocument();
    });

    test('accepts PNG files', async () => {
      const user = userEvent.setup();
      render(<QRUploadDialog {...defaultProps} />);

      const file = createMockFile('qr-code.png', 1024 * 100, 'image/png');
      const input = screen.getByLabelText('Select QR code image');

      await user.upload(input, file);

      await waitFor(() => {
        expect(screen.getByAltText('QR code preview')).toBeInTheDocument();
      });
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    test('accepts JPEG files', async () => {
      const user = userEvent.setup();
      render(<QRUploadDialog {...defaultProps} />);

      const file = createMockFile('qr-code.jpg', 1024 * 100, 'image/jpeg');
      const input = screen.getByLabelText('Select QR code image');

      await user.upload(input, file);

      await waitFor(() => {
        expect(screen.getByAltText('QR code preview')).toBeInTheDocument();
      });
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    test('accepts WEBP files', async () => {
      const user = userEvent.setup();
      render(<QRUploadDialog {...defaultProps} />);

      const file = createMockFile('qr-code.webp', 1024 * 100, 'image/webp');
      const input = screen.getByLabelText('Select QR code image');

      await user.upload(input, file);

      await waitFor(() => {
        expect(screen.getByAltText('QR code preview')).toBeInTheDocument();
      });
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    test('file input has correct accept attribute', () => {
      render(<QRUploadDialog {...defaultProps} />);

      const input = screen.getByLabelText('Select QR code image') as HTMLInputElement;
      expect(input.accept).toBe('.png,.jpg,.jpeg,.webp');
    });
  });

  describe('upload submission', () => {
    test('calls onUpload with selected file', async () => {
      const user = userEvent.setup();
      const onUpload = vi.fn().mockResolvedValue(undefined);
      render(<QRUploadDialog {...defaultProps} onUpload={onUpload} />);

      const file = createMockFile('qr-code.png', 1024 * 100, 'image/png');
      const input = screen.getByLabelText('Select QR code image');

      await user.upload(input, file);
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /upload/i })).toBeEnabled();
      });

      await user.click(screen.getByRole('button', { name: /upload/i }));

      await waitFor(() => {
        expect(onUpload).toHaveBeenCalledWith(file);
      });
    });

    test('calls onClose on cancel', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(<QRUploadDialog {...defaultProps} onClose={onClose} />);

      await user.click(screen.getByRole('button', { name: /cancel/i }));

      expect(onClose).toHaveBeenCalled();
    });

    test('triggers file input click when upload area is clicked', () => {
      const clickSpy = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {});
      render(<QRUploadDialog {...defaultProps} />);

      fireEvent.click(screen.getByText(/Click to select an image/i));

      expect(clickSpy).toHaveBeenCalled();
      clickSpy.mockRestore();
    });
  });

  describe('loading state', () => {
    test('disables buttons when loading', () => {
      render(<QRUploadDialog {...defaultProps} isLoading={true} />);

      expect(screen.getByRole('button', { name: /uploading/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
    });

    test('shows progress indicator and uploading text when loading', () => {
      render(<QRUploadDialog {...defaultProps} isLoading={true} />);

      // Check for the "Uploading..." text that appears with the progress indicator
      const uploadingTexts = screen.getAllByText(/Uploading/i);
      expect(uploadingTexts.length).toBeGreaterThan(0);
    });
  });
});
