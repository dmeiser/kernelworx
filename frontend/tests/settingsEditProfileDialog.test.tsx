/**
 * Tests for the settings-page EditProfileDialog component.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EditProfileDialog } from '../src/components/settings/EditProfileDialog';

const makeHook = (overrides = {}) => ({
  editDialogOpen: true,
  givenName: 'John',
  familyName: 'Doe',
  city: 'Austin',
  state: 'TX',
  unitType: 'Pack',
  unitNumber: '42',
  setEditDialogOpen: vi.fn(),
  setGivenName: vi.fn(),
  setFamilyName: vi.fn(),
  setCity: vi.fn(),
  setState: vi.fn(),
  setUnitType: vi.fn(),
  setUnitNumber: vi.fn(),
  ...overrides,
});

describe('settings EditProfileDialog', () => {
  it('renders all fields when open', () => {
    render(<EditProfileDialog profileHook={makeHook() as never} updating={false} onSave={vi.fn()} />);
    expect(screen.getByText('Edit Profile Information')).toBeInTheDocument();
    expect(screen.getByLabelText(/First Name/i)).toHaveValue('John');
    expect(screen.getByRole('button', { name: /Save Changes/i })).toBeInTheDocument();
  });

  it('shows Saving label when updating', () => {
    render(<EditProfileDialog profileHook={makeHook() as never} updating={true} onSave={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Saving/i })).toBeInTheDocument();
  });

  it('calls setEditDialogOpen when cancel is clicked', async () => {
    const userEvent = (await import('@testing-library/user-event')).default;
    const user = userEvent.setup();
    const hook = makeHook();
    render(<EditProfileDialog profileHook={hook as never} updating={false} onSave={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Cancel/i }));
    expect(hook.setEditDialogOpen).toHaveBeenCalledWith(false);
  });

  it('invokes change handlers for all fields', () => {
    const hook = makeHook();
    render(<EditProfileDialog profileHook={hook as never} updating={false} onSave={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/First Name/i), { target: { value: 'Jane' } });
    fireEvent.change(screen.getByLabelText(/Last Name/i), { target: { value: 'Roe' } });
    fireEvent.change(screen.getByLabelText(/City/i), { target: { value: 'Dallas' } });
    fireEvent.change(screen.getByLabelText(/State/i), { target: { value: 'tx' } });
    fireEvent.change(screen.getByLabelText(/Unit Number/i), { target: { value: '7' } });
    expect(hook.setGivenName).toHaveBeenCalledWith('Jane');
    expect(hook.setFamilyName).toHaveBeenCalledWith('Roe');
    expect(hook.setCity).toHaveBeenCalledWith('Dallas');
    expect(hook.setState).toHaveBeenCalled();
    expect(hook.setUnitNumber).toHaveBeenCalledWith('7');
  });

  it('invokes dialog close handler', async () => {
    const userEvent = (await import('@testing-library/user-event')).default;
    const user = userEvent.setup();
    const hook = makeHook();
    render(<EditProfileDialog profileHook={hook as never} updating={false} onSave={vi.fn()} />);
    await user.keyboard('{Escape}');
    expect(hook.setEditDialogOpen).toHaveBeenCalledWith(false);
  });
});
