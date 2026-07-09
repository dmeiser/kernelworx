/**
 * Tests for StoryPage
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StoryPage } from '../src/pages/StoryPage';
import { BrowserRouter } from 'react-router-dom';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const renderStoryPage = () =>
  render(
    <BrowserRouter>
      <StoryPage />
    </BrowserRouter>,
  );

describe('StoryPage', () => {
  it('renders the story heading', () => {
    renderStoryPage();
    expect(screen.getByRole('heading', { name: 'The Story of KernelWorx' })).toBeInTheDocument();
  });

  it('renders key story content', () => {
    renderStoryPage();
    expect(screen.getByText(/Cub Scout dad/i)).toBeInTheDocument();
    expect(screen.getByText(/paper order sheets/i)).toBeInTheDocument();
    expect(screen.getByText(/QR codes/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Pack Kernel/i).length).toBeGreaterThan(0);
  });

  it('renders the GitHub sponsors link', () => {
    renderStoryPage();
    const link = screen.getByRole('link', { name: /Sponsor KernelWorx/i });
    expect(link).toHaveAttribute('href', 'https://github.com/sponsors/dmeiser');
  });
});
