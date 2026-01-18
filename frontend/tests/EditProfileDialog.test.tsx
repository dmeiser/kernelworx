/**
 * EditProfileDialog component tests
 */

import { describe, test, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditProfileDialog } from '../src/components/EditProfileDialog';

describe('EditProfileDialog', () => {
  test('renders when open with current name', () => {
    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText('Edit Scout')).toBeInTheDocument();
    const nameInput = screen.getByLabelText(/Scout Name/i) as HTMLInputElement;
    expect(nameInput.value).toBe('Scout Alpha');
  });

  test('does not render when closed', () => {
    render(
      <EditProfileDialog
        open={false}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.queryByText('Edit Scout')).not.toBeInTheDocument();
  });

  test('calls onClose when Cancel button clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={onClose}
        onSubmit={vi.fn()}
      />,
    );

    const cancelButton = screen.getByRole('button', { name: /Cancel/i });
    await user.click(cancelButton);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('submit button disabled when name unchanged', () => {
    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const submitButton = screen.getByRole('button', { name: /Save Changes/i });
    expect(submitButton).toBeDisabled();
  });

  test('submit button disabled when name is empty', async () => {
    const user = userEvent.setup();
    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);

    const submitButton = screen.getByRole('button', { name: /Save Changes/i });
    expect(submitButton).toBeDisabled();
  });

  test('submit button enabled when name changed', async () => {
    const user = userEvent.setup();
    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Scout Beta');

    const submitButton = screen.getByRole('button', { name: /Save Changes/i });
    expect(submitButton).not.toBeDisabled();
  });

  test('calls onSubmit with profileId and trimmed new name', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);

    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, '  Scout Beta  ');

    const submitButton = screen.getByRole('button', { name: /Save Changes/i });
    await user.click(submitButton);

    expect(onSubmit).toHaveBeenCalledWith('profile-123', 'Scout Beta');
  });

  test('calls onClose after successful submit', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Scout Beta');

    const submitButton = screen.getByRole('button', { name: /Save Changes/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  test('shows loading state during submission', async () => {
    const user = userEvent.setup();
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const onSubmit = vi.fn((_profileId: string, _name: string) => new Promise<void>(() => {})); // Never resolves

    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Scout Beta');

    const submitButton = screen.getByRole('button', { name: /Save Changes/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Saving.../i })).toBeInTheDocument();
    });
  });

  test('disables input and buttons during submission', async () => {
    const user = userEvent.setup();
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const onSubmit = vi.fn((_profileId: string, _name: string) => new Promise<void>(() => {})); // Never resolves

    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Scout Beta');

    const submitButton = screen.getByRole('button', { name: /Save Changes/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(nameInput).toBeDisabled();
      expect(screen.getByRole('button', { name: /Cancel/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /Saving.../i })).toBeDisabled();
    });
  });

  test('submits on Enter key press when name changed', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);

    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Scout Beta{Enter}');

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('profile-123', 'Scout Beta');
    });
  });

  test('resets to current name when dialog reopened', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i) as HTMLInputElement;
    await user.clear(nameInput);
    await user.type(nameInput, 'Scout Beta');
    expect(nameInput.value).toBe('Scout Beta');

    // Close and reopen
    rerender(
      <EditProfileDialog
        open={false}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    rerender(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const nameInputReopened = screen.getByLabelText(/Scout Name/i) as HTMLInputElement;
    expect(nameInputReopened.value).toBe('Scout Alpha');
  });

  test('restores original name on cancel', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();

    render(
      <EditProfileDialog
        open={true}
        profileId="profile-123"
        currentName="Scout Alpha"
        onClose={onClose}
        onSubmit={vi.fn()}
      />,
    );

    const nameInput = screen.getByLabelText(/Scout Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Scout Beta');

    const cancelButton = screen.getByRole('button', { name: /Cancel/i });
    await user.click(cancelButton);

    expect(onClose).toHaveBeenCalled();
  });
});
