/**
 * Tests for CreatePaymentMethodDialog component
 */

import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { CreatePaymentMethodDialog } from '../src/components/CreatePaymentMethodDialog';

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  onCreate: vi.fn().mockResolvedValue(undefined),
  existingNames: ['Venmo', 'PayPal'],
  reservedNames: ['cash', 'check'],
  isLoading: false,
};

describe('CreatePaymentMethodDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rendering', () => {
    it('renders dialog when open', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByText('Create Payment Method')).toBeInTheDocument();
    });

    it('does not render dialog when closed', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} open={false} />);

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('renders name input field', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      expect(screen.getByLabelText('Payment method name')).toBeInTheDocument();
    });

    it('renders create and cancel buttons', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      expect(screen.getByRole('button', { name: /create/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    });
  });

  describe('validation', () => {
    it('disables Create button when name is empty', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      const createButton = screen.getByRole('button', { name: /create/i });
      expect(createButton).toBeDisabled();
    });

    it('enables Create button when name has content', async () => {
      const user = userEvent.setup();
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Zelle');

      const createButton = screen.getByRole('button', { name: /create/i });
      expect(createButton).toBeEnabled();
    });

    it('shows error for reserved name', async () => {
      const user = userEvent.setup();
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Cash');
      await user.click(screen.getByRole('button', { name: /create/i }));

      await waitFor(() => {
        expect(screen.getByText(/"Cash" is a reserved payment method name/i)).toBeInTheDocument();
      });
    });

    it('shows error when submitting empty name via Enter key', async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockResolvedValue(undefined);
      render(<CreatePaymentMethodDialog {...defaultProps} onCreate={onCreate} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, '{Enter}');

      await waitFor(() => {
        expect(screen.getByText(/name is required/i)).toBeInTheDocument();
      });
      expect(onCreate).not.toHaveBeenCalled();
    });

    it('shows error when name exceeds maximum length', async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockResolvedValue(undefined);
      render(<CreatePaymentMethodDialog {...defaultProps} onCreate={onCreate} />);

      const input = screen.getByLabelText('Payment method name') as HTMLInputElement;
      const longName = 'A'.repeat(51);
      fireEvent.change(input, { target: { value: longName } });
      await user.click(screen.getByRole('button', { name: /create/i }));

      await waitFor(() => {
        expect(screen.getByText(/Name must be 50 characters or less/i)).toBeInTheDocument();
      });
      expect(onCreate).not.toHaveBeenCalled();
    });

    it('shows error for duplicate name', async () => {
      const user = userEvent.setup();
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Venmo');
      await user.click(screen.getByRole('button', { name: /create/i }));

      await waitFor(() => {
        expect(screen.getByText(/already exists/i)).toBeInTheDocument();
      });
    });

    it('clears error when user types after validation failure', async () => {
      const user = userEvent.setup();
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Venmo');
      await user.click(screen.getByRole('button', { name: /create/i }));

      await waitFor(() => {
        expect(screen.getByText(/already exists/i)).toBeInTheDocument();
      });

      await user.clear(input);
      await user.type(input, 'Zelle');

      await waitFor(() => {
        expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument();
      });
    });

    it('limits input to 50 characters via maxLength', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} />);

      const input = screen.getByLabelText('Payment method name') as HTMLInputElement;
      expect(input.maxLength).toBe(50);
    });
  });

  describe('submission', () => {
    it('calls onCreate with trimmed name on submit', async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockResolvedValue(undefined);
      render(<CreatePaymentMethodDialog {...defaultProps} onCreate={onCreate} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, '  Zelle  ');
      await user.click(screen.getByRole('button', { name: /create/i }));

      await waitFor(() => {
        expect(onCreate).toHaveBeenCalledWith('Zelle');
      });
    });

    it('calls onClose on cancel', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(<CreatePaymentMethodDialog {...defaultProps} onClose={onClose} />);

      await user.click(screen.getByRole('button', { name: /cancel/i }));

      expect(onClose).toHaveBeenCalled();
    });

    it('submits on Enter key', async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockResolvedValue(undefined);
      render(<CreatePaymentMethodDialog {...defaultProps} onCreate={onCreate} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Zelle{Enter}');

      await waitFor(() => {
        expect(onCreate).toHaveBeenCalledWith('Zelle');
      });
    });

    it('does not close dialog when onCreate rejects', async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockRejectedValue(new Error('Creation failed'));
      const onClose = vi.fn();
      render(<CreatePaymentMethodDialog {...defaultProps} onCreate={onCreate} onClose={onClose} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Zelle');
      await user.click(screen.getByRole('button', { name: /create/i }));

      await waitFor(() => {
        expect(onCreate).toHaveBeenCalledWith('Zelle');
      });
      expect(onClose).not.toHaveBeenCalled();
    });

    it('does not submit on non-Enter keys', async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockResolvedValue(undefined);
      render(<CreatePaymentMethodDialog {...defaultProps} onCreate={onCreate} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Zelle{Escape}');

      expect(onCreate).not.toHaveBeenCalled();
    });

    it('does not submit on Enter key while loading', async () => {
      const user = userEvent.setup();
      const onCreate = vi.fn().mockResolvedValue(undefined);
      render(<CreatePaymentMethodDialog {...defaultProps} onCreate={onCreate} isLoading={true} />);

      const input = screen.getByLabelText('Payment method name');
      await user.type(input, 'Zelle{Enter}');

      expect(onCreate).not.toHaveBeenCalled();
    });
  });

  describe('loading state', () => {
    it('disables buttons when loading', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} isLoading={true} />);

      expect(screen.getByRole('button', { name: /creating/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
    });

    it('disables input when loading', () => {
      render(<CreatePaymentMethodDialog {...defaultProps} isLoading={true} />);

      expect(screen.getByLabelText('Payment method name')).toBeDisabled();
    });
  });
});
