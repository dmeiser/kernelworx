/**
 * CatalogsPage - Manage product catalogs (public and user-owned)
 */

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useLazyQuery } from "@apollo/client/react";
import { useAuth } from "../contexts/AuthContext";
import {
  Box,
  Button,
  Typography,
  Alert,
  CircularProgress,
  Stack,
  Paper,
  Tabs,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Chip,
} from "@mui/material";
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Public as PublicIcon,
  Lock as PrivateIcon,
} from "@mui/icons-material";
import { CatalogEditorDialog } from "../components/CatalogEditorDialog";
import {
  LIST_PUBLIC_CATALOGS,
  LIST_MY_CATALOGS,
  LIST_MY_PROFILES,
  LIST_SHARED_PROFILES,
  LIST_SEASONS_BY_PROFILE,
  CREATE_CATALOG,
  UPDATE_CATALOG,
  DELETE_CATALOG,
} from "../lib/graphql";

interface Product {
  productId: string;
  productName: string;
  description?: string;
  price: number;
}

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
  ownerAccountId?: string;
  isPublic: boolean;
  products: Product[];
  createdAt: string;
  updatedAt: string;
}

export const CatalogsPage: React.FC = () => {
  const { account } = useAuth();
  const [currentTab, setCurrentTab] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingCatalog, setEditingCatalog] = useState<Catalog | null>(null);

  // Fetch public catalogs
  const {
    data: publicData,
    loading: publicLoading,
    error: publicError,
    refetch: refetchPublic,
  } = useQuery<{ listPublicCatalogs: Catalog[] }>(LIST_PUBLIC_CATALOGS);

  // Fetch user's catalogs
  const {
    data: myData,
    loading: myLoading,
    error: myError,
    refetch: refetchMy,
  } = useQuery<{ listMyCatalogs: Catalog[] }>(LIST_MY_CATALOGS);

  // Fetch user's profiles to check catalog usage
  const { data: myProfilesData } = useQuery<{ listMyProfiles: any[] }>(
    LIST_MY_PROFILES,
  );
  const { data: sharedProfilesData } = useQuery<{
    listSharedProfiles: any[];
  }>(LIST_SHARED_PROFILES);

  // Get all user's profile IDs
  const allUserProfiles = [
    ...(myProfilesData?.listMyProfiles || []),
    ...(sharedProfilesData?.listSharedProfiles || []),
  ];

  // State to track catalogs in use
  const [catalogsInUse, setCatalogsInUse] = useState<Set<string>>(new Set());

  // Lazy query for fetching seasons
  const [fetchSeasons] = useLazyQuery<{ listSeasonsByProfile: any[] }>(
    LIST_SEASONS_BY_PROFILE,
  );

  // Fetch seasons for all profiles and determine catalog usage
  useEffect(() => {
    const fetchAllSeasons = async () => {
      const catalogIds = new Set<string>();

      // Fetch seasons for each profile sequentially to respect Hooks rules
      for (const profile of allUserProfiles) {
        if (profile.profileId) {
          try {
            const { data } = await fetchSeasons({
              variables: { profileId: profile.profileId },
            });

            data?.listSeasonsByProfile.forEach((season) => {
              if (season.catalogId) {
                catalogIds.add(season.catalogId);
              }
            });
          } catch (error) {
            console.error(`Failed to fetch seasons for profile ${profile.profileId}:`, error);
          }
        }
      }

      setCatalogsInUse(catalogIds);
    };

    if (allUserProfiles.length > 0) {
      fetchAllSeasons();
    }
  }, [myProfilesData, sharedProfilesData, fetchSeasons]);

  // Create catalog
  const [createCatalog] = useMutation(CREATE_CATALOG, {
    onCompleted: () => {
      refetchPublic();
      refetchMy();
    },
  });

  // Update catalog
  const [updateCatalog] = useMutation(UPDATE_CATALOG, {
    onCompleted: () => {
      refetchPublic();
      refetchMy();
    },
  });

  // Delete catalog
  const [deleteCatalog] = useMutation(DELETE_CATALOG, {
    onCompleted: () => {
      refetchPublic();
      refetchMy();
    },
  });

  const publicCatalogs = publicData?.listPublicCatalogs || [];
  const myPrivateCatalogs = myData?.listMyCatalogs || [];

  // Combine private catalogs with public catalogs I own
  const myCatalogs = [
    ...myPrivateCatalogs,
    ...publicCatalogs.filter((catalog) =>
      myPrivateCatalogs.every((myCat) => myCat.catalogId !== catalog.catalogId),
    ),
  ];

  const handleCreateCatalog = () => {
    setEditingCatalog(null);
    setEditorOpen(true);
  };

  const handleEditCatalog = (catalog: Catalog) => {
    setEditingCatalog(catalog);
    setEditorOpen(true);
  };

  const handleDeleteCatalog = async (
    catalogId: string,
    catalogName: string,
  ) => {
    if (
      confirm(
        `Are you sure you want to delete "${catalogName}"? This action cannot be undone.`,
      )
    ) {
      await deleteCatalog({ variables: { catalogId } });
    }
  };

  const handleSaveCatalog = async (catalogData: {
    catalogName: string;
    isPublic: boolean;
    products: Array<{
      productName: string;
      description?: string;
      price: number;
    }>;
  }) => {
    if (editingCatalog) {
      // Update existing
      await updateCatalog({
        variables: {
          catalogId: editingCatalog.catalogId,
          input: catalogData,
        },
      });
    } else {
      // Create new
      await createCatalog({
        variables: {
          input: catalogData,
        },
      });
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const renderCatalogTable = (
    catalogs: Catalog[],
    showActionsColumn: boolean,
    catalogsInUse: Set<string>,
  ) => {
    if (catalogs.length === 0) {
      return (
        <Paper sx={{ p: 4, textAlign: "center" }}>
          <Typography color="text.secondary">
            {showActionsColumn
              ? "No catalogs yet. Create your first catalog!"
              : "No public catalogs available."}
          </Typography>
        </Paper>
      );
    }

    return (
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Catalog Name</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Products</TableCell>
              <TableCell>Created</TableCell>
              {showActionsColumn && <TableCell align="right">Actions</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {catalogs.map((catalog) => (
              <TableRow key={catalog.catalogId} hover>
                <TableCell>
                  <Stack direction="row" spacing={1} alignItems="center">
                    {catalog.isPublic ? (
                      <PublicIcon fontSize="small" color="primary" />
                    ) : (
                      <PrivateIcon fontSize="small" color="action" />
                    )}
                    <Typography fontWeight="medium">
                      {catalog.catalogName}
                    </Typography>
                  </Stack>
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={1}>
                    <Chip
                      label={catalog.isPublic ? "Public" : "Private"}
                      size="small"
                      color={catalog.isPublic ? "primary" : "default"}
                    />
                    {catalogsInUse.has(catalog.catalogId) && (
                      <Chip
                        label="In Use"
                        size="small"
                        color="success"
                        variant="outlined"
                      />
                    )}
                  </Stack>
                </TableCell>
                <TableCell>{catalog.products.length} items</TableCell>
                <TableCell>{formatDate(catalog.createdAt)}</TableCell>
                {showActionsColumn && (
                  <TableCell align="right">
                    {/* Only show actions if user owns this catalog */}
                    {catalog.ownerAccountId === account?.accountId && (
                      <Stack
                        direction="row"
                        spacing={1}
                        justifyContent="flex-end"
                      >
                        <IconButton
                          size="small"
                          onClick={() => handleEditCatalog(catalog)}
                          color="primary"
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                        <IconButton
                          size="small"
                          onClick={() =>
                            handleDeleteCatalog(
                              catalog.catalogId,
                              catalog.catalogName,
                            )
                          }
                          color="error"
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    )}
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    );
  };

  if (publicLoading || myLoading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="200px"
      >
        <CircularProgress />
      </Box>
    );
  }

  if (publicError || myError) {
    return (
      <Alert severity="error">
        Failed to load catalogs: {publicError?.message || myError?.message}
      </Alert>
    );
  }

  return (
    <Box>
      {/* Header */}
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        mb={3}
      >
        <Typography variant="h4">Product Catalogs</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={handleCreateCatalog}
        >
          New Catalog
        </Button>
      </Stack>

      {/* Info Alert */}
      <Alert severity="info" sx={{ mb: 3 }}>
        <Typography variant="body2">
          <strong>Public catalogs</strong> are visible to all users and can be
          used by anyone when creating seasons.
          <strong> Private catalogs</strong> are only visible to you and can be
          used for your own tracking.
        </Typography>
      </Alert>

      {/* Tabs */}
      <Paper sx={{ mb: 3 }}>
        <Tabs
          value={currentTab}
          onChange={(_, newValue) => setCurrentTab(newValue)}
          variant="fullWidth"
        >
          <Tab label="My Catalogs" />
          <Tab label="Public Catalogs" />
        </Tabs>
      </Paper>

      {/* Tab Content */}
      {currentTab === 0 && renderCatalogTable(myCatalogs, true, catalogsInUse)}
      {currentTab === 1 &&
        renderCatalogTable(publicCatalogs, false, catalogsInUse)}

      {/* Editor Dialog */}
      <CatalogEditorDialog
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSave={handleSaveCatalog}
        initialCatalog={editingCatalog}
      />
    </Box>
  );
};
