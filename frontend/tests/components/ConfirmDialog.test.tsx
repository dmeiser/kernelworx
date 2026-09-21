import { describe, test, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConfirmDialog } from '../../src/components/ConfirmDialog';

describe('ConfirmDialog error handling', () => {
  test('confirms and closes when onConfirm resolves', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<ConfirmDialog open title="Delete item" onClose={onClose} onConfirm={onConfirm} confirmLabel="Delete" />);

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  test('surfaces Error rejections with their message and allows dismissal', async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error('delete exploded'));
    const onDismissError = vi.fn();
    render(
      <ConfirmDialog open title="Delete item" onClose={vi.fn()} onConfirm={onConfirm} onDismissError={onDismissError} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.getByText('delete exploded')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onDismissError).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('delete exploded')).not.toBeInTheDocument();
  });

  test('surfaces a generic message for non-Error rejections', async () => {
    const onConfirm = vi.fn().mockRejectedValue('boom-string');
    render(<ConfirmDialog open title="Delete item" onClose={vi.fn()} onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.getByText('An unexpected error occurred')).toBeInTheDocument());
  });

  test('renders default copy from confirmLabel when no children are provided', () => {
    render(<ConfirmDialog open title="Deactivate" onClose={vi.fn()} onConfirm={vi.fn()} confirmLabel="Deactivate" />);

    expect(screen.getByText(/Are you sure you want to deactivate\?/i)).toBeInTheDocument();
  });
});
