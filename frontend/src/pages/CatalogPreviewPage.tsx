/**
 * CatalogPreviewPage - Preview catalog contents and create campaigns
 *
 * Displays all products in a catalog with the ability to create
 * a campaign or shared campaign using this catalog.
 */

import React, { useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import {
  Box,
  Button,
  Typography,
  Alert,
  CircularProgress,
  Stack,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
} from '@mui/material';
import {
  Add as AddIcon,
  Share as ShareIcon,
  ArrowBack as BackIcon,
} from '@mui/icons-material';
import { GET_CATALOG } from '../lib/graphql';
import type { Catalog, Product } from '../types';

interface CatalogPreviewPageProps {
  onCreateCampaign?: (catalogId: string) => void;
  onCreateSharedCampaign?: (catalogId: string) => void;
}

export const CatalogPreviewPage: React.FC<CatalogPreviewPageProps> = ({
  onCreateCampaign,
  onCreateSharedCampaign,
}) => {
  const { catalogId: catalogUuid } = useParams<{ catalogId: string }>();
  const navigate = useNavigate();

  // Add CATALOG# prefix if not present
  const catalogId = catalogUuid?.startsWith('CATALOG#') ? catalogUuid : `CATALOG#${catalogUuid}`;

  React.useEffect(() => {
    localStorage.setItem('catalogPreviewPageLoaded', JSON.stringify({ catalogId, timestamp: new Date().toISOString() }));
  }, [catalogId]);

  if (!catalogId) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">No catalog ID provided</Alert>
      </Box>
    );
  }

  const { data, loading, error } = useQuery<{ getCatalog: Catalog }>(GET_CATALOG, {
    variables: { catalogId },
  });

  const catalog: Catalog | undefined = data?.getCatalog;
  const products: Product[] = useMemo(() => catalog?.products || [], [catalog?.products]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">Error loading catalog: {error.message}</Alert>
      </Box>
    );
  }

  if (!catalog) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="warning">Catalog not found</Alert>
      </Box>
    );
  }

  const handleCreateCampaign = () => {
    if (onCreateCampaign) {
      onCreateCampaign(catalogId);
    } else {
      navigate('/create-campaign', { state: { catalogId } });
    }
  };

  const handleCreateSharedCampaign = () => {
    if (onCreateSharedCampaign) {
      onCreateSharedCampaign(catalogId);
    } else {
      navigate('/shared-campaigns/create', { state: { catalogId } });
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      {/* Back button and header */}
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 3 }}>
        <Button
          startIcon={<BackIcon />}
          onClick={() => navigate('/catalogs')}
          variant="outlined"
        >
          Back
        </Button>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5" sx={{ fontWeight: 600 }}>
            {catalog.catalogName}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {products.length} product{products.length !== 1 ? 's' : ''}
          </Typography>
        </Box>
      </Stack>

      {/* Catalog info and action buttons */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between">
          <Stack direction="row" spacing={2}>
            <Chip
              label={catalog.catalogType === 'ADMIN_MANAGED' ? 'Admin-Managed' : 'User-Created'}
              variant="outlined"
              color={catalog.catalogType === 'ADMIN_MANAGED' ? 'primary' : 'secondary'}
            />
            {catalog.isPublic && <Chip label="Public" variant="filled" />}
          </Stack>
          <Stack direction="row" spacing={1}>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={handleCreateCampaign}
            >
              Create Campaign
            </Button>
            <Button
              variant="outlined"
              startIcon={<ShareIcon />}
              onClick={handleCreateSharedCampaign}
            >
              Create Shared Campaign
            </Button>
          </Stack>
        </Stack>
      </Paper>

      {/* Products table */}
      {products.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">No products in this catalog</Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead sx={{ backgroundColor: '#f5f5f5' }}>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>Product Name</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Description</TableCell>
                <TableCell align="right" sx={{ fontWeight: 600 }}>
                  Price
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {products.map((product) => (
                <TableRow key={product.productId} hover>
                  <TableCell sx={{ fontWeight: 500 }}>{product.productName}</TableCell>
                  <TableCell sx={{ maxWidth: 300, whiteSpace: 'normal' }}>
                    {product.description || '-'}
                  </TableCell>
                  <TableCell align="right">${product.price.toFixed(2)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Action buttons at bottom */}
      <Stack direction="row" spacing={2} sx={{ mt: 3, justifyContent: 'center' }}>
        <Button
          variant="contained"
          size="large"
          startIcon={<AddIcon />}
          onClick={handleCreateCampaign}
        >
          Create Campaign
        </Button>
        <Button
          variant="outlined"
          size="large"
          startIcon={<ShareIcon />}
          onClick={handleCreateSharedCampaign}
        >
          Create Shared Campaign
        </Button>
      </Stack>
    </Box>
  );
};

export default CatalogPreviewPage;
