/**
 * Main App component
 *
 * Sets up routing, authentication, Apollo Client, and theme.
 */

import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Suspense, lazy, useEffect } from 'react';
import { Box, CircularProgress, CssBaseline, ThemeProvider } from '@mui/material';
import { ApolloProvider } from '@apollo/client/react';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ErrorBoundary } from './components/ErrorBoundary';
import { DevFooter } from './components/DevFooter';
import { apolloClient } from './lib/apollo';
import { theme } from './lib/theme';
import { AppLayout } from './components/AppLayout';
import { RouteErrorBoundary } from './components/RouteErrorBoundary';

function lazyRoute(factory: () => Promise<{ default: React.ComponentType }>): React.FC {
  const LazyComponent = lazy(factory);
  return function LazyRouteWrapper() {
    return (
      <RouteErrorBoundary>
        <LazyComponent />
      </RouteErrorBoundary>
    );
  };
}

const LandingPage = lazyRoute(() => import('./pages/LandingPage').then((m) => ({ default: m.LandingPage })));
const LoginPage = lazyRoute(() => import('./pages/LoginPage').then((m) => ({ default: m.LoginPage })));
const ForgotPasswordPage = lazyRoute(() =>
  import('./pages/ForgotPasswordPage').then((m) => ({ default: m.ForgotPasswordPage })),
);
const SignupPage = lazyRoute(() => import('./pages/SignupPage').then((m) => ({ default: m.SignupPage })));
const PrivacyPolicyPage = lazyRoute(() =>
  import('./pages/PrivacyPolicyPage').then((m) => ({ default: m.PrivacyPolicyPage })),
);
const ScoutsPage = lazyRoute(() => import('./pages/ScoutsPage').then((m) => ({ default: m.ScoutsPage })));
const ScoutCampaignsPage = lazyRoute(() =>
  import('./pages/ScoutCampaignsPage').then((m) => ({ default: m.ScoutCampaignsPage })),
);
const ScoutManagementPage = lazyRoute(() =>
  import('./pages/ScoutManagementPage').then((m) => ({ default: m.ScoutManagementPage })),
);
const CampaignLayout = lazyRoute(() => import('./pages/CampaignLayout').then((m) => ({ default: m.CampaignLayout })));
const SettingsPage = lazyRoute(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const UserSettingsPage = lazyRoute(() =>
  import('./pages/UserSettingsPage').then((m) => ({ default: m.UserSettingsPage })),
);
const AcceptInvitePage = lazyRoute(() =>
  import('./pages/AcceptInvitePage').then((m) => ({ default: m.AcceptInvitePage })),
);
const AdminPage = lazyRoute(() => import('./pages/AdminPage').then((m) => ({ default: m.AdminPage })));
const UserDataPage = lazyRoute(() => import('./pages/UserDataPage').then((m) => ({ default: m.UserDataPage })));
const CatalogsPage = lazyRoute(() => import('./pages/CatalogsPage').then((m) => ({ default: m.CatalogsPage })));
const CatalogPreviewPage = lazyRoute(() =>
  import('./pages/CatalogPreviewPage').then((m) => ({ default: m.CatalogPreviewPage })),
);
const CampaignReportsPage = lazyRoute(() =>
  import('./pages/CampaignReportsPage').then((m) => ({ default: m.CampaignReportsPage })),
);
const CreateCampaignPage = lazyRoute(() =>
  import('./pages/CreateCampaignPage').then((m) => ({ default: m.CreateCampaignPage })),
);
const SharedCampaignsPage = lazyRoute(() =>
  import('./pages/SharedCampaignsPage').then((m) => ({ default: m.SharedCampaignsPage })),
);
const CreateSharedCampaignPage = lazyRoute(() =>
  import('./pages/CreateSharedCampaignPage').then((m) => ({ default: m.CreateSharedCampaignPage })),
);
const PaymentMethodsPage = lazyRoute(() =>
  import('./pages/PaymentMethodsPage').then((m) => ({ default: m.PaymentMethodsPage })),
);
const HomePage = lazyRoute(() => import('./pages/HomePage').then((m) => ({ default: m.HomePage })));
const StoryPage = lazyRoute(() => import('./pages/StoryPage').then((m) => ({ default: m.StoryPage })));

function ScrollToHash() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const behavior = prefersReducedMotion ? ('auto' as const) : ('smooth' as const);
      if (hash) {
        const id = hash.replace('#', '');
        const element = document.getElementById(id);
        if (element) {
          element.scrollIntoView({ behavior });
        }
      } else {
        window.scrollTo({ top: 0, behavior });
      }
    }, 0);
    return () => clearTimeout(timeoutId);
  }, [pathname, hash]);

  return null;
}

function PageLoader() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
      <CircularProgress />
    </Box>
  );
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>;
}

function ProtectedAppRoute({ children, requireAdmin }: { children: React.ReactNode; requireAdmin?: boolean }) {
  const { pathname } = useLocation();
  return (
    <ProtectedRoute requireAdmin={requireAdmin}>
      <AppLayout>
        <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>
      </AppLayout>
    </ProtectedRoute>
  );
}

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ApolloProvider client={apolloClient}>
        <BrowserRouter>
          <AuthProvider>
            <Suspense fallback={<PageLoader />}>
              <ScrollToHash />
              <Routes>
                {/* Public routes */}
                <Route
                  path="/"
                  element={
                    <PublicRoute>
                      <LandingPage />
                    </PublicRoute>
                  }
                />
                <Route
                  path="/login"
                  element={
                    <PublicRoute>
                      <LoginPage />
                    </PublicRoute>
                  }
                />
                <Route
                  path="/forgot-password"
                  element={
                    <PublicRoute>
                      <ForgotPasswordPage />
                    </PublicRoute>
                  }
                />
                <Route
                  path="/signup"
                  element={
                    <PublicRoute>
                      <SignupPage />
                    </PublicRoute>
                  }
                />
                <Route
                  path="/privacy"
                  element={
                    <PublicRoute>
                      <PrivacyPolicyPage />
                    </PublicRoute>
                  }
                />
                <Route
                  path="/story"
                  element={
                    <PublicRoute>
                      <StoryPage />
                    </PublicRoute>
                  }
                />

                {/* Shared Campaign short-link route */}
                <Route
                  path="/c/:sharedCampaignCode"
                  element={
                    <ProtectedAppRoute>
                      <CreateCampaignPage />
                    </ProtectedAppRoute>
                  }
                />

                {/* Manual create campaign route */}
                <Route
                  path="/create-campaign"
                  element={
                    <ProtectedAppRoute>
                      <CreateCampaignPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/accept-invite"
                  element={
                    <ProtectedAppRoute>
                      <AcceptInvitePage />
                    </ProtectedAppRoute>
                  }
                />

                {/* Protected routes */}
                <Route
                  path="/home"
                  element={
                    <ProtectedAppRoute>
                      <HomePage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/scouts"
                  element={
                    <ProtectedAppRoute>
                      <ScoutsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/scouts/:profileId/campaigns"
                  element={
                    <ProtectedAppRoute>
                      <ScoutCampaignsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/scouts/:profileId/manage"
                  element={
                    <ProtectedAppRoute>
                      <ScoutManagementPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/scouts/:profileId/campaigns/:campaignId/*"
                  element={
                    <ProtectedAppRoute>
                      <CampaignLayout />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/settings"
                  element={
                    <ProtectedAppRoute>
                      <SettingsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/account/settings"
                  element={
                    <ProtectedAppRoute>
                      <UserSettingsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/catalogs/:catalogId/preview"
                  element={
                    <ProtectedAppRoute>
                      <CatalogPreviewPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/catalogs"
                  element={
                    <ProtectedAppRoute>
                      <CatalogsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/campaign-reports"
                  element={
                    <ProtectedAppRoute>
                      <CampaignReportsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/shared-campaigns"
                  element={
                    <ProtectedAppRoute>
                      <SharedCampaignsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/shared-campaigns/create"
                  element={
                    <ProtectedAppRoute>
                      <CreateSharedCampaignPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/payment-methods"
                  element={
                    <ProtectedAppRoute>
                      <PaymentMethodsPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/admin"
                  element={
                    <ProtectedAppRoute requireAdmin>
                      <AdminPage />
                    </ProtectedAppRoute>
                  }
                />

                <Route
                  path="/admin/user-data/:accountId"
                  element={
                    <ProtectedAppRoute requireAdmin>
                      <UserDataPage />
                    </ProtectedAppRoute>
                  }
                />

                {/* 404 catch-all */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
            <DevFooter />
          </AuthProvider>
        </BrowserRouter>
      </ApolloProvider>
    </ThemeProvider>
  );
}

export default App;
