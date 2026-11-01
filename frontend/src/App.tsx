import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Suspense, lazy } from 'react';
import { Box, CircularProgress, CssBaseline, ThemeProvider } from '@mui/material';
import { ApolloProvider } from '@apollo/client/react';
import { ErrorBoundary } from './components/ErrorBoundary';
import { apolloClient } from './lib/apollo';
import { publicApolloClient } from './lib/publicApollo';
import { theme } from './lib/theme';
import { RouteErrorBoundary } from './components/RouteErrorBoundary';

const AuthedRoutes = lazy(() => import('./AuthedRoutes').then((m) => ({ default: m.default })));

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

const PublicOrderPage = lazyRoute(() =>
  import('./pages/PublicOrderPage').then((m) => ({ default: m.PublicOrderPage })),
);
const PublicReceiptPage = lazyRoute(() =>
  import('./pages/PublicReceiptPage').then((m) => ({ default: m.PublicReceiptPage })),
);

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return <ErrorBoundary resetKey={pathname}>{children}</ErrorBoundary>;
}

function PageLoader() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '50vh' }}>
      <CircularProgress />
    </Box>
  );
}

function PublicOrderApollo({ children }: { children: React.ReactNode }) {
  return <ApolloProvider client={publicApolloClient}>{children}</ApolloProvider>;
}

function AppShell() {
  const { pathname } = useLocation();
  const isPublicOrder = /^\/(o|r)\//.test(pathname);
  if (isPublicOrder) {
    return (
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route
            path="/o/:campaignId/:token"
            element={
              <PublicRoute>
                <PublicOrderApollo>
                  <PublicOrderPage />
                </PublicOrderApollo>
              </PublicRoute>
            }
          />
          <Route
            path="/r/:campaignId/:orderSuffix/:receiptToken"
            element={
              <PublicRoute>
                <PublicOrderApollo>
                  <PublicReceiptPage />
                </PublicOrderApollo>
              </PublicRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    );
  }
  return (
    <Suspense fallback={<PageLoader />}>
      <AuthedRoutes />
    </Suspense>
  );
}

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ApolloProvider client={apolloClient}>
        <BrowserRouter>
          <AppShell />
        </BrowserRouter>
      </ApolloProvider>
    </ThemeProvider>
  );
}

export default App;