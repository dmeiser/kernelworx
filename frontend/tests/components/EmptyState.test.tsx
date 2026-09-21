import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EmptyState } from '../../src/components/EmptyState';
import { Add as AddIcon } from '@mui/icons-material';

describe('EmptyState', () => {
  it('renders the message only when no title or action is provided', () => {
    render(<EmptyState message="Nothing here yet" />);

    expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders a title above the message', () => {
    render(<EmptyState title="No campaigns" message="Create your first campaign to get started" />);

    expect(screen.getByText('No campaigns')).toBeInTheDocument();
    expect(screen.getByText('Create your first campaign to get started')).toBeInTheDocument();
  });

  it('renders an action button without an icon', () => {
    const onAction = vi.fn();
    render(<EmptyState message="Empty" actionLabel="Start over" onAction={onAction} />);

    const button = screen.getByRole('button', { name: 'Start over' });
    fireEvent.click(button);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('renders an action button with an icon', () => {
    const onAction = vi.fn();
    render(<EmptyState message="Empty" actionLabel="Add item" actionIcon={AddIcon} onAction={onAction} />);

    const button = screen.getByRole('button', { name: 'Add item' });
    fireEvent.click(button);
    expect(onAction).toHaveBeenCalledTimes(1);
  });
});
