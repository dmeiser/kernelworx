/**
 * Main App component
 *
 * Sets up routing, authentication, Apollo Client, and theme.
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { CssBaseline, ThemeProvider } from '@mui/material';
import { ApolloProvider } from '@apollo/client/react';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { DevFooter } from './components/DevFooter';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { SignupPage } from './pages/SignupPage';
import { ScoutsPage } from './pages/ScoutsPage';
import { ScoutCampaignsPage } from './pages/ScoutCampaignsPage';
import { ScoutManagementPage } from './pages/ScoutManagementPage';
import { CampaignLayout } from './pages/CampaignLayout';
import { SettingsPage } from './pages/SettingsPage';
import { UserSettingsPage } from './pages/UserSettingsPage';
import { AcceptInvitePage } from './pages/AcceptInvitePage';
import { AdminPage } from './pages/AdminPage';
import { CatalogsPage } from './pages/CatalogsPage';
import { CatalogPreviewPage } from './pages/CatalogPreviewPage';
import { CampaignReportsPage } from './pages/CampaignReportsPage';
import { CreateCampaignPage } from './pages/CreateCampaignPage';
import { SharedCampaignsPage } from './pages/SharedCampaignsPage';
import { CreateSharedCampaignPage } from './pages/CreateSharedCampaignPage';
import { PaymentMethodsPage } from './pages/PaymentMethodsPage';
import { apolloClient } from './lib/apollo';
import { theme } from './lib/theme';
import { AppLayout } from './components/AppLayout';

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ApolloProvider client={apolloClient}>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              {/* Public routes */}
              <Route path="/" element={<LandingPage />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<SignupPage />} />

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
