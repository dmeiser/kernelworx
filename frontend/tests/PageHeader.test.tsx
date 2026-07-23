import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PageHeader } from '../src/components/PageHeader';
import { Settings as SettingsIcon } from '@mui/icons-material';

describe('PageHeader', () => {
  it('renders title and subtitle', () => {
    render(<PageHeader title="Settings" subtitle="Manage your account" />);

    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByText('Manage your account')).toBeInTheDocument();
  });

  it('renders back button with label', () => {
    const onClick = vi.fn();
    render(<PageHeader title="Page" backButton={{ onClick, label: 'Back' }} />);

    const button = screen.getByRole('button', { name: /back/i });
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    expect(onClick).toHaveBeenCalled();
  });

  it('renders icon back button when no label is provided', () => {
    const onClick = vi.fn();
    render(<PageHeader title="Page" backButton={{ onClick, 'aria-label': 'Go back' }} />);

    const button = screen.getByRole('button', { name: /go back/i });
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    expect(onClick).toHaveBeenCalled();
  });

  it('renders action slot', () => {
    render(<PageHeader title="Page" action={<button>Action</button>} />);

    expect(screen.getByRole('button', { name: /action/i })).toBeInTheDocument();
  });

  it('renders icon next to title', () => {
    render(<PageHeader title="Page" icon={SettingsIcon} />);

    expect(screen.getByText('Page')).toBeInTheDocument();
  });

  it('renders children', () => {
    render(<PageHeader title="Page">Child content</PageHeader>);

    expect(screen.getByText('Child content')).toBeInTheDocument();
  });
});
