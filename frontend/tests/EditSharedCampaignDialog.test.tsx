import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditSharedCampaignDialog } from '../src/components/EditSharedCampaignDialog';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const baseSharedCampaign = {
  sharedCampaignCode: 'SC-TEST',
  catalogId: 'CAT#1',
  campaignName: 'Test Campaign',
  campaignYear: 2025,
  unitType: 'Pack',
  unitNumber: 1,
  city: 'Town',
  state: 'ST',
  createdBy: 'user#1',
  createdByName: 'User',
  createdByAccountId: 'ACCOUNT#user1',
  creatorMessage: 'Hello scouts',
  description: 'Internal note',
  isActive: true,
  createdAt: new Date().toISOString(),
  catalog: {
    catalogId: 'CAT#1',
    catalogName: 'Popcorn 2025',
  },
};

describe('EditSharedCampaignDialog', () => {
  let onClose: ReturnType<typeof vi.fn>;
  let onSave: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    onClose = vi.fn();
    onSave = vi.fn(() => Promise.resolve());
  });

  it('renders initial values and calls onSave', async () => {
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    // initial values present
    expect(screen.getByDisplayValue('Internal note')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Hello scouts')).toBeInTheDocument();

    // Change description and save
    const descriptionInput = screen.getByLabelText(/Description \(For Your Reference\)/i);
    fireEvent.change(descriptionInput, { target: { value: 'New desc' } });

    const saveButton = screen.getByRole('button', { name: /save changes/i });
    fireEvent.click(saveButton);

    // onSave should be called with updated values
    expect(onSave).toHaveBeenCalled();
  });

  it('shows validation error for long creator message', async () => {
    render(
      <EditSharedCampaignDialog
        open={true}
        sharedCampaign={{ ...baseSharedCampaign, creatorMessage: '' }}
        onClose={onClose}
        onSave={onSave}
      />,
    );

    const creatorInput = screen.getByLabelText(/Message to Scouts/i);
    const longMsg = 'x'.repeat(500);
    fireEvent.change(creatorInput, { target: { value: longMsg } });

    const saveButton = screen.getByRole('button', { name: /save changes/i });
    fireEvent.click(saveButton);

    expect(screen.getByText(/Creator message must be/)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('renders read-only campaign details', () => {
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    expect(screen.getByText('Campaign Details (Read-Only)')).toBeInTheDocument();
    expect(screen.getByText('SC-TEST')).toBeInTheDocument();
    expect(screen.getByText('Popcorn 2025')).toBeInTheDocument();
    expect(screen.getByText(/Test Campaign 2025/)).toBeInTheDocument();
    expect(screen.getByText(/Pack 1, Town, ST/)).toBeInTheDocument();
    // Status chip displays 'Active' - use getAllByText since it appears in both the chip and switch label
    expect(screen.getAllByText('Active').length).toBeGreaterThanOrEqual(1);
  });

  it('renders inactive status chip', () => {
    render(
      <EditSharedCampaignDialog
        open={true}
        sharedCampaign={{ ...baseSharedCampaign, isActive: false }}
        onClose={onClose}
        onSave={onSave}
      />,
    );

    expect(screen.getByText('Inactive')).toBeInTheDocument();
  });

  it('renders "Unknown Catalog" when catalog is missing', () => {
    const { catalog: _, ...noCatalog } = baseSharedCampaign;
    render(
      <EditSharedCampaignDialog
        open={true}
        sharedCampaign={noCatalog as typeof baseSharedCampaign}
        onClose={onClose}
        onSave={onSave}
      />,
    );

    expect(screen.getByText('Unknown Catalog')).toBeInTheDocument();
  });

  it('toggles isActive switch', async () => {
    const user = userEvent.setup();
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    // Toggle the Active switch - MUI Switch renders an input[type=checkbox] inside
    const toggle = document.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(toggle).not.toBeNull();
    await user.click(toggle);

    // Now save - should send isActive: false
    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith('SC-TEST', expect.objectContaining({ isActive: false }));
    });
  });

  it('updates creator message', async () => {
    const user = userEvent.setup();
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    const input = screen.getByLabelText(/Message to Scouts/i);
    await user.clear(input);
    await user.type(input, 'Updated message');

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(
        'SC-TEST',
        expect.objectContaining({ creatorMessage: 'Updated message' }),
      );
    });
  });

  it('cancel closes the dialog', async () => {
    const user = userEvent.setup();
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('save button is disabled when no changes made', () => {
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    const saveButton = screen.getByRole('button', { name: /save changes/i });
    expect(saveButton).toBeDisabled();
  });

  it('shows error when onSave throws', async () => {
    onSave.mockRejectedValue(new Error('Save failed'));
    const user = userEvent.setup();
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    // Make a change so Save button is enabled
    const input = screen.getByLabelText(/Description/i);
    await user.clear(input);
    await user.type(input, 'Changed');

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByText('Save failed')).toBeInTheDocument();
    });
  });

  it('shows generic error for non-Error throws', async () => {
    onSave.mockRejectedValue('plain error');
    const user = userEvent.setup();
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    const input = screen.getByLabelText(/Description/i);
    await user.clear(input);
    await user.type(input, 'Changed');

    await user.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(screen.getByText(/Failed to update/)).toBeInTheDocument();
    });
  });

  it('shows character count for creator message', () => {
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    expect(screen.getByText(/12\/300 characters/)).toBeInTheDocument();
  });

  it('renders campaign link with code', () => {
    render(
      <EditSharedCampaignDialog open={true} sharedCampaign={baseSharedCampaign} onClose={onClose} onSave={onSave} />,
    );

    expect(screen.getByText(/\/c\/SC-TEST/)).toBeInTheDocument();
  });
});
