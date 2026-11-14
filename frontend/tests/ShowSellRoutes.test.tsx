/**
 * The preview gate at the route (§1.6).
 *
 * Nothing in Show & Sell is reachable outside the `show-sell-preview` group, and the
 * route is where that is decided: a session still loading is not an off switch, and
 * an off switch must not leave the screens mounted behind it.
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ShowSellRoutes } from '../src/ShowSellRoutes';

const preview = vi.fn();

// The gate's children are lazy on purpose (the preview is a slice of the bundle);
// the question here is only whether the gate opens, so each route is a marker.
vi.mock('../src/pages/UnitsPage', () => ({ UnitsPage: () => <p>Units screen</p> }));
vi.mock('../src/pages/UnitCampaignJoinPage', () => ({ UnitCampaignJoinPage: () => <p>Join screen</p> }));
vi.mock('../src/hooks/useShowSellPreview', () => ({
  SHOW_SELL_PREVIEW_GROUP: 'show-sell-preview',
  useShowSellPreview: () => preview(),
}));

// The gate's children are lazy on purpose (the preview is a slice of the bundle).
// Here the question is only whether the gate opens, so each route stands in for a
// marker rather than for the screen behind it.

function renderRoutes(path: string, mocks: unknown[] = []) {
  render(
    <MockedProvider mocks={mocks as never}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<p>Landing</p>} />
          <Route path="/show-sell/*" element={<ShowSellRoutes />} />
        </Routes>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('ShowSellRoutes', () => {
  it('waits for the session instead of refusing a screen it may allow', () => {
    preview.mockReturnValue({ enabled: false, loading: true });

    renderRoutes('/show-sell/units');

    expect(document.querySelector('.MuiCircularProgress-root')).toBeInTheDocument();
    expect(screen.queryByText('Landing')).not.toBeInTheDocument();
  });

  it('sends an account outside the preview group back to the app', async () => {
    preview.mockReturnValue({ enabled: false, loading: false });

    renderRoutes('/show-sell/units');

    expect(await screen.findByText('Landing')).toBeInTheDocument();
  });

  it('opens the preview screens for an account in the group', async () => {
    preview.mockReturnValue({ enabled: true, loading: false });

    renderRoutes('/show-sell/units');
    expect(await screen.findByText('Units screen')).toBeInTheDocument();

    renderRoutes('/show-sell/join');
    expect(await screen.findByText('Join screen')).toBeInTheDocument();
  });
});
