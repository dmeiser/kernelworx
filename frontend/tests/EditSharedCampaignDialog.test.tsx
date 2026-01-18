import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { EditSharedCampaignDialog } from '../src/components/EditSharedCampaignDialog';
import { describe, it, expect, vi } from 'vitest';

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
  creatorMessage: 'Hello scouts',
  description: 'Internal note',
  isActive: true,
  createdAt: new Date().toISOString(),
};

describe('EditSharedCampaignDialog', () => {
  it('renders initial values and calls onSave', async () => {
    const onClose = vi.fn();
    const onSave = vi.fn(() => Promise.resolve());

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
    const onClose = vi.fn();
    const onSave = vi.fn(() => Promise.resolve());

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
});
