/**
 * Tests for StoryPage
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StoryPage } from '../src/pages/StoryPage';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from '../src/contexts/AuthContext';
import * as amplifyAuth from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  signInWithRedirect: vi.fn(),
  getCurrentUser: vi.fn(),
}));

vi.mock('aws-amplify/utils', () => ({
  Hub: {
    listen: vi.fn(() => vi.fn()),
  },
}));

const renderStoryPage = () =>
  render(
    <BrowserRouter>
      <AuthProvider>
        <StoryPage />
      </AuthProvider>
    </BrowserRouter>,
  );

describe('StoryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: undefined,
    } as any);
  });

  it('renders the story heading', () => {
    renderStoryPage();
    expect(screen.getByRole('heading', { name: 'The Story of KernelWorx' })).toBeInTheDocument();
  });

  it('renders key story content', () => {
    renderStoryPage();
    expect(screen.getByText(/parent and den leader/i)).toBeInTheDocument();
    expect(screen.getByText(/supporters/i)).toBeInTheDocument();
    expect(screen.getByText(/harder than it needed to be/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Pack Kernel/i).length).toBeGreaterThan(0);
  });

  it('renders the GitHub sponsors link', () => {
    renderStoryPage();
    const link = screen.getByRole('link', { name: /Sponsor KernelWorx/i });
    expect(link).toHaveAttribute('href', 'https://github.com/sponsors/dmeiser');
  });
});
