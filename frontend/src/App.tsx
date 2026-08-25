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
import { DevFooter } from './components/DevFooter';
import { apolloClient } from './lib/apollo';
import { theme } from './lib/theme';
import { AppLayout } from './components/AppLayout';

const LandingPage = lazy(() => import('./pages/LandingPage').then((m) => ({ default: m.LandingPage })));
const LoginPage = lazy(() => import('./pages/LoginPage').then((m) => ({ default: m.LoginPage })));
const ForgotPasswordPage = lazy(() =>
  import('./pages/ForgotPasswordPage').then((m) => ({ default: m.ForgotPasswordPage })),
);
const SignupPage = lazy(() => import('./pages/SignupPage').then((m) => ({ default: m.SignupPage })));
const PrivacyPolicyPage = lazy(() =>
  import('./pages/PrivacyPolicyPage').then((m) => ({ default: m.PrivacyPolicyPage })),
);
const ScoutsPage = lazy(() => import('./pages/ScoutsPage').then((m) => ({ default: m.ScoutsPage })));
const ScoutCampaignsPage = lazy(() =>
  import('./pages/ScoutCampaignsPage').then((m) => ({ default: m.ScoutCampaignsPage })),
);
const ScoutManagementPage = lazy(() =>
  import('./pages/ScoutManagementPage').then((m) => ({ default: m.ScoutManagementPage })),
);
const CampaignLayout = lazy(() => import('./pages/CampaignLayout').then((m) => ({ default: m.CampaignLayout })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const UserSettingsPage = lazy(() =>
  import('./pages/UserSettingsPage').then((m) => ({ default: m.UserSettingsPage })),
);
const AcceptInvitePage = lazy(() =>
  import('./pages/AcceptInvitePage').then((m) => ({ default: m.AcceptInvitePage })),
);
const AdminPage = lazy(() => import('./pages/AdminPage').then((m) => ({ default: m.AdminPage })));
const UserDataPage = lazy(() => import('./pages/UserDataPage').then((m) => ({ default: m.UserDataPage })));
const CatalogsPage = lazy(() => import('./pages/CatalogsPage').then((m) => ({ default: m.CatalogsPage })));
const CatalogPreviewPage = lazy(() =>
  import('./pages/CatalogPreviewPage').then((m) => ({ default: m.CatalogPreviewPage })),
);
const CampaignReportsPage = lazy(() =>
  import('./pages/CampaignReportsPage').then((m) => ({ default: m.CampaignReportsPage })),
);
const CreateCampaignPage = lazy(() =>
  import('./pages/CreateCampaignPage').then((m) => ({ default: m.CreateCampaignPage })),
);
const SharedCampaignsPage = lazy(() =>
  import('./pages/SharedCampaignsPage').then((m) => ({ default: m.SharedCampaignsPage })),
);
const CreateSharedCampaignPage = lazy(() =>
  import('./pages/CreateSharedCampaignPage').then((m) => ({ default: m.CreateSharedCampaignPage })),
);
const PaymentMethodsPage = lazy(() =>
  import('./pages/PaymentMethodsPage').then((m) => ({ default: m.PaymentMethodsPage })),
);
const HomePage = lazy(() => import('./pages/HomePage').then((m) => ({ default: m.HomePage })));
const StoryPage = lazy(() => import('./pages/StoryPage').then((m) => ({ default: m.StoryPage })));

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

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ApolloProvider client={apolloClient}>
        <BrowserRouter>
          <ScrollToHash />
          <AuthProvider>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                {/* Public routes */}
                <Route path="/" element={<LandingPage />} />
                <Route path="/login" element={<LoginPage />} />
                <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                <Route path="/signup" element={<SignupPage />} />
                <Route path="/privacy" element={<PrivacyPolicyPage />} />
                <Route path="/story" element={<StoryPage />} />

                {/* Shared Campaign short-link route */}
                <Route
                  path="/c/:sharedCampaignCode"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <CreateCampaignPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                {/* Manual create campaign route */}
                <Route
                  path="/create-campaign"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <CreateCampaignPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/accept-invite"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <AcceptInvitePage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                {/* Protected routes */}
                <Route
                  path="/home"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <HomePage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/scouts"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <ScoutsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/scouts/:profileId/campaigns"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <ScoutCampaignsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/scouts/:profileId/manage"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <ScoutManagementPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/scouts/:profileId/campaigns/:campaignId/*"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <CampaignLayout />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/settings"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <SettingsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/account/settings"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <UserSettingsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/catalogs/:catalogId/preview"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <CatalogPreviewPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/catalogs"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <CatalogsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/campaign-reports"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <CampaignReportsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/shared-campaigns"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <SharedCampaignsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/shared-campaigns/create"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <CreateSharedCampaignPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/payment-methods"
                  element={
                    <ProtectedRoute>
                      <AppLayout>
                        <PaymentMethodsPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/admin"
                  element={
                    <ProtectedRoute requireAdmin>
                      <AppLayout>
                        <AdminPage />
                      </AppLayout>
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/admin/user-data/:accountId"
                  element={
                    <ProtectedRoute requireAdmin>
                      <AppLayout>
                        <UserDataPage />
                      </AppLayout>
                    </ProtectedRoute>
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
