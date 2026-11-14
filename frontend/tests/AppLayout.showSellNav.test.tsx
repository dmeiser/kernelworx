/**
 * Show & Sell navigation is hidden and shown by the same flag as the routes.
 *
 * A preview account that is offered a link and then refused by the route is the
 * failure mode this pairing prevents; an account outside the group should never see
 * the links at all.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { BrowserRouter } from 'react-router-dom';
import { AppLayout } from '../src/components/AppLayout';
import { LIST_MY_SHARED_CAMPAIGNS } from '../src/lib/graphql';
import type { Account } from '../src/types/auth';

const navigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => navigate };
});

const preview = vi.fn();
vi.mock('../src/hooks/useShowSellPreview', () => ({
  SHOW_SELL_PREVIEW_GROUP: 'show-sell-preview',
  useShowSellPreview: () => preview(),
}));

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    account: {
      accountId: 'ACCOUNT#avery',
      email: 'avery@example.com',
      givenName: 'Avery',
      familyName: 'Admin',
      isAdmin: false,
    } as Account,
    logout: vi.fn(),
  }),
}));

beforeEach(() => {
  navigate.mockReset();
});

function renderLayout() {
  render(
    <MockedProvider
      mocks={[
        { request: { query: LIST_MY_SHARED_CAMPAIGNS }, result: { data: { mySharedCampaigns: [] } } },
      ] as never}
    >
      <BrowserRouter>
        <AppLayout>
          <p>Page</p>
        </AppLayout>
      </BrowserRouter>
    </MockedProvider>,
  );
}

describe('AppLayout Show & Sell navigation', () => {
  it('offers Units and the join screen to a preview account, and routes both', async () => {
    preview.mockReturnValue({ enabled: true, loading: false });
    renderLayout();

    await userEvent.setup().click(await screen.findByTestId('nav-units'));
    expect(navigate).toHaveBeenCalledWith('/show-sell/units');

    await userEvent.setup().click(await screen.findByTestId('nav-join-campaign'));
    expect(navigate).toHaveBeenCalledWith('/show-sell/join');
  });

  it('hides both links from an account outside the preview group', async () => {
    preview.mockReturnValue({ enabled: false, loading: false });
    renderLayout();

    expect(await screen.findByText('Page')).toBeInTheDocument();
    expect(screen.queryByTestId('nav-units')).not.toBeInTheDocument();
    expect(screen.queryByTestId('nav-join-campaign')).not.toBeInTheDocument();
  });
});
