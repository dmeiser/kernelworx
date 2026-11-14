/**
 * Show & Sell routes, gated behind the `show-sell-preview` Cognito group.
 *
 * The gate belongs at the route rather than inside each page: every screen here
 * calls a Unit resolver, and an account outside the group has no grant to resolve,
 * so it would spend the round trip learning nothing. Gating the route also keeps
 * the navigation honest — the links are hidden by the same flag that hides the
 * screens, so a preview user is never offered a page that then refuses them.
 *
 * A flag off means nothing about the data: Units and campaigns a Unit admin
 * already holds stay exactly where they are; only this browser path is closed.
 */

import React, { Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Box, CircularProgress } from '@mui/material';
import { useShowSellPreview } from './hooks/useShowSellPreview';

function lazyRoute(factory: () => Promise<{ default: React.ComponentType }>): React.FC {
  const Component = React.lazy(factory);
  return () => (
    <Suspense
      fallback={
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
          <CircularProgress />
        </Box>
      }
    >
      <Component />
    </Suspense>
  );
}

const UnitsPage = lazyRoute(() => import('./pages/UnitsPage').then((m) => ({ default: m.UnitsPage })));
const UnitWorkspacePage = lazyRoute(() =>
  import('./pages/UnitWorkspacePage').then((m) => ({ default: m.UnitWorkspacePage })),
);
const UnitCampaignWorkspacePage = lazyRoute(() =>
  import('./pages/UnitCampaignWorkspacePage').then((m) => ({ default: m.UnitCampaignWorkspacePage })),
);
const UnitCampaignJoinPage = lazyRoute(() =>
  import('./pages/UnitCampaignJoinPage').then((m) => ({ default: m.UnitCampaignJoinPage })),
);

export const ShowSellRoutes: React.FC = () => {
  const { enabled, loading } = useShowSellPreview();

  // Loading is not "off": redirecting while the session is still resolving would
  // bounce a preview user out of a screen they are allowed to see.
  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
        <CircularProgress />
      </Box>
    );
  }
  if (!enabled) return <Navigate to="/" replace />;

  return (
    <Routes>
      <Route path="units" element={<UnitsPage />} />
      <Route path="units/:unitId" element={<UnitWorkspacePage />} />
      <Route path="units/:unitId/campaigns/:unitCampaignId" element={<UnitCampaignWorkspacePage />} />
      <Route path="join" element={<UnitCampaignJoinPage />} />
      <Route path="*" element={<Navigate to="units" replace />} />
    </Routes>
  );
};
