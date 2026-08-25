/**
 * Main App component
 *
 * Sets up routing, authentication, Apollo Client, and theme.
 */

import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import { CssBaseline, ThemeProvider } from '@mui/material';
import { ApolloProvider } from '@apollo/client/react';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ErrorBoundary } from './components/ErrorBoundary';
import { DevFooter } from './components/DevFooter';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { ForgotPasswordPage } from './pages/ForgotPasswordPage';
import { SignupPage } from './pages/SignupPage';
import { PrivacyPolicyPage } from './pages/PrivacyPolicyPage';
import { ScoutsPage } from './pages/ScoutsPage';
import { ScoutCampaignsPage } from './pages/ScoutCampaignsPage';
import { ScoutManagementPage } from './pages/ScoutManagementPage';
import { CampaignLayout } from './pages/CampaignLayout';
import { SettingsPage } from './pages/SettingsPage';
import { UserSettingsPage } from './pages/UserSettingsPage';
import { AcceptInvitePage } from './pages/AcceptInvitePage';
import { AdminPage } from './pages/AdminPage';
import { UserDataPage } from './pages/UserDataPage';
import { CatalogsPage } from './pages/CatalogsPage';
import { CatalogPreviewPage } from './pages/CatalogPreviewPage';
import { CampaignReportsPage } from './pages/CampaignReportsPage';
import { CreateCampaignPage } from './pages/CreateCampaignPage';
import { SharedCampaignsPage } from './pages/SharedCampaignsPage';
import { CreateSharedCampaignPage } from './pages/CreateSharedCampaignPage';
import { PaymentMethodsPage } from './pages/PaymentMethodsPage';
import { HomePage } from './pages/HomePage';
import { StoryPage } from './pages/StoryPage';
import { apolloClient } from './lib/apollo';
import { theme } from './lib/theme';
import { AppLayout } from './components/AppLayout';

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

function PublicRoute({ children }: { children: React.ReactNode }) {
  return <ErrorBoundary>{children}</ErrorBoundary>;
}

function ProtectedAppRoute({ children, requireAdmin }: { children: React.ReactNode; requireAdmin?: boolean }) {
  return (
    <ProtectedRoute requireAdmin={requireAdmin}>
      <AppLayout>
        <ErrorBoundary>{children}</ErrorBoundary>
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
          <ScrollToHash />
          <AuthProvider>
            <Routes>
              {/* Public routes */}
              <Route path="/" element={<PublicRoute><LandingPage /></PublicRoute>} />
              <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
              <Route path="/forgot-password" element={<PublicRoute><ForgotPasswordPage /></PublicRoute>} />
              <Route path="/signup" element={<PublicRoute><SignupPage /></PublicRoute>} />
              <Route path="/privacy" element={<PublicRoute><PrivacyPolicyPage /></PublicRoute>} />
              <Route path="/story" element={<PublicRoute><StoryPage /></PublicRoute>} />

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
            <DevFooter />
          </AuthProvider>
        </BrowserRouter>
      </ApolloProvider>
    </ThemeProvider>
  );
}

export default App;
