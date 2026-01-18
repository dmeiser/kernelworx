/**
 * CreateProfileDialog component tests
 */

import { describe, test, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CreateProfileDialog } from '../src/components/CreateProfileDialog';

describe('CreateProfileDialog', () => {
  test('renders when open', () => {
    render(<CreateProfileDialog open={true} onClose={vi.fn()} onSubmit={vi.fn()} />);

    expect(screen.getByText('Create New Scout')).toBeInTheDocument();
    expect(screen.getByLabelText(/Scout Name/i)).toBeInTheDocument();
  });

  test('does not render when closed', () => {
    render(<CreateProfileDialog open={false} onClose={vi.fn()} onSubmit={vi.fn()} />);

    expect(screen.queryByText('Create New Scout')).not.toBeInTheDocument();
  });

  test('calls onClose when Cancel button clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(<CreateProfileDialog open={true} onClose={onClose} onSubmit={vi.fn()} />);

    const cancelButton = screen.getByRole('button', { name: /Cancel/i });
    await user.click(cancelButton);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('submit button disabled when name is empty', () => {
    render(<CreateProfileDialog open={true} onClose={vi.fn()} onSubmit={vi.fn()} />);

    const submitButton = screen.getByRole('button', { name: /Create Scout/i });
    expect(submitButton).toBeDisabled();
  });

  test('submit button enabled when name has text', async () => {
    const user = userEvent.setup();
    render(<CreateProfileDialog open={true} onClose={vi.fn()} onSubmit={vi.fn()} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, 'Scout Alpha');

    const submitButton = screen.getByRole('button', { name: /Create Scout/i });
    expect(submitButton).not.toBeDisabled();
  });

  test('calls onSubmit with trimmed name when form submitted', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(<CreateProfileDialog open={true} onClose={onClose} onSubmit={onSubmit} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, '  Scout Alpha  ');

    const submitButton = screen.getByRole('button', { name: /Create Scout/i });
    await user.click(submitButton);

    expect(onSubmit).toHaveBeenCalledWith('Scout Alpha');
  });

  test('calls onClose after successful submit', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(<CreateProfileDialog open={true} onClose={onClose} onSubmit={onSubmit} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, 'Scout Alpha');

    const submitButton = screen.getByRole('button', { name: /Create Scout/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  test('shows loading state during submission', async () => {
    const user = userEvent.setup();
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const onSubmit = vi.fn((_name: string) => new Promise<void>(() => {})); // Never resolves

    render(<CreateProfileDialog open={true} onClose={vi.fn()} onSubmit={onSubmit} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, 'Scout Alpha');

    const submitButton = screen.getByRole('button', { name: /Create Scout/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Creating.../i })).toBeInTheDocument();
    });
  });

  test('disables input and buttons during submission', async () => {
    const user = userEvent.setup();
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const onSubmit = vi.fn((_name: string) => new Promise<void>(() => {})); // Never resolves

    render(<CreateProfileDialog open={true} onClose={vi.fn()} onSubmit={onSubmit} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, 'Scout Alpha');

    const submitButton = screen.getByRole('button', { name: /Create Scout/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(nameInput).toBeDisabled();
      expect(screen.getByRole('button', { name: /Cancel/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /Creating.../i })).toBeDisabled();
    });
  });

  test('submits on Enter key press', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);

    render(<CreateProfileDialog open={true} onClose={vi.fn()} onSubmit={onSubmit} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, 'Scout Alpha{Enter}');

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('Scout Alpha');
    });
  });

  test('clears input when dialog closed', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(<CreateProfileDialog open={true} onClose={onClose} onSubmit={vi.fn()} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, 'Scout Alpha');

    const cancelButton = screen.getByRole('button', { name: /Cancel/i });
    await user.click(cancelButton);

    expect(onClose).toHaveBeenCalled();
  });

  test('does not submit when name is only whitespace', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(<CreateProfileDialog open={true} onClose={vi.fn()} onSubmit={onSubmit} />);

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.type(nameInput, '   ');

    const submitButton = screen.getByRole('button', { name: /Create Scout/i });
    expect(submitButton).toBeDisabled();
  });
});
