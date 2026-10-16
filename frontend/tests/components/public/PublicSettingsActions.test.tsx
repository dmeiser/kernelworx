/**
 * Tests for PublicSettingsActions.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PublicSettingsActions } from '../../../src/components/public/PublicSettingsActions';

const renderActions = (overrides: Partial<Parameters<typeof PublicSettingsActions>[0]> = {}) => {
  const props = {
    onSave: vi.fn(),
    onRotate: vi.fn(),
    onDisable: vi.fn(),
    onEnable: vi.fn(),
    enabled: true,
    saving: false,
    ...overrides,
  };
  render(<PublicSettingsActions {...props} />);
  return props;
};

describe('PublicSettingsActions', () => {
  it('invokes each handler when its button is clicked', () => {
    const props = renderActions();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    fireEvent.click(screen.getByRole('button', { name: 'Rotate Share Token' }));
    fireEvent.click(screen.getByRole('button', { name: 'Disable' }));
    expect(props.onSave).toHaveBeenCalledTimes(1);
    expect(props.onRotate).toHaveBeenCalledTimes(1);
    expect(props.onDisable).toHaveBeenCalledTimes(1);
  });

  it('invokes onEnable when disabled', () => {
    const props = renderActions({ enabled: false });
    fireEvent.click(screen.getByRole('button', { name: 'Enable' }));
    expect(props.onEnable).toHaveBeenCalledTimes(1);
  });

  it('disables save/enable/disable while saving and shows the pending label', () => {
    renderActions({ saving: true });
    const pendingButtons = screen.getAllByRole('button', { name: 'Saving...' });
    expect(pendingButtons).toHaveLength(3);
    for (const button of pendingButtons) {
      expect(button).toBeDisabled();
    }
    expect(screen.getByRole('button', { name: 'Rotate Share Token' })).toBeDisabled();
  });

  it('disables enable when the prerequisites are unmet', () => {
    const props = renderActions({ enabled: false, canEnable: false });
    const enable = screen.getByRole('button', { name: 'Enable' });
    expect(enable).toBeDisabled();
    fireEvent.click(enable);
    expect(props.onEnable).not.toHaveBeenCalled();
  });

  it('disables enable when already enabled and disable when not', () => {
    const { unmount } = render(
      <PublicSettingsActions
        onSave={vi.fn()}
        onRotate={vi.fn()}
        onDisable={vi.fn()}
        onEnable={vi.fn()}
        enabled
        saving={false}
      />,
    );
    expect(screen.getByRole('button', { name: 'Enable' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Disable' })).toBeEnabled();
    unmount();
    render(
      <PublicSettingsActions
        onSave={vi.fn()}
        onRotate={vi.fn()}
        onDisable={vi.fn()}
        onEnable={vi.fn()}
        enabled={false}
        saving={false}
      />,
    );
    expect(screen.getByRole('button', { name: 'Enable' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Disable' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Rotate Share Token' })).toBeDisabled();
  });
});
