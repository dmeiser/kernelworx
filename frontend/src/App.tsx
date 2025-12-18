/**
 * Main App component
 *
 * Sets up routing, authentication, Apollo Client, and theme.
 */

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { ApolloProvider } from "@apollo/client/react";
import { AuthProvider } from "./contexts/AuthContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LandingPage } from "./pages/LandingPage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { ProfileSeasonsPage } from "./pages/ProfileSeasonsPage";
import { SellerProfileManagementPage } from "./pages/SellerProfileManagementPage";
import { SeasonLayout } from "./pages/SeasonLayout";
import { SettingsPage } from "./pages/SettingsPage";
import { UserSettingsPage } from "./pages/UserSettingsPage";
import { AcceptInvitePage } from "./pages/AcceptInvitePage";
import { AdminPage } from "./pages/AdminPage";
import { CatalogsPage } from "./pages/CatalogsPage";
import { apolloClient } from "./lib/apollo";
import { theme } from "./lib/theme";
import { AppLayout } from "./components/AppLayout";

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
                path="/profiles"
                element={
                  <ProtectedRoute>
                    <AppLayout>
                      <ProfilesPage />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/profiles/:profileId/seasons"
                element={
                  <ProtectedRoute>
                    <AppLayout>
                      <ProfileSeasonsPage />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/profiles/:profileId/manage"
                element={
                  <ProtectedRoute>
                    <AppLayout>
                      <SellerProfileManagementPage />
                    </AppLayout>
                  </ProtectedRoute>
                }
              />

              <Route
                path="/profiles/:profileId/seasons/:seasonId/*"
                element={
                  <ProtectedRoute>
                    <AppLayout>
                      <SeasonLayout />
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
          </AuthProvider>
        </BrowserRouter>
      </ApolloProvider>
    </ThemeProvider>
  );
}

export default App;
