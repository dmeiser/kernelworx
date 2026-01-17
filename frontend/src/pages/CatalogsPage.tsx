/**
 * CatalogsPage - Manage product catalogs (public and user-owned)
 */

import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useLazyQuery } from '@apollo/client/react';
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
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Visibility as VisibilityIcon,
} from '@mui/icons-material';
import { CatalogEditorDialog } from '../components/CatalogEditorDialog';
import {
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  LIST_MY_PROFILES,
  LIST_MY_SHARES,
  LIST_CAMPAIGNS_BY_PROFILE,
  CREATE_CATALOG,
  UPDATE_CATALOG,
  DELETE_CATALOG,
} from '../lib/graphql';
import { ensureProfileId } from '../lib/ids';
import type { Catalog } from '../types';

// Helper: Format date for display
const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
};

// Helper: Merge owned profiles with shared profiles
const mergeProfiles = (
  myProfilesData: { listMyProfiles: Array<{ profileId: string }> } | undefined,
  sharedProfilesData: { listMyShares: { profileId: string; permissions: string[] }[] } | undefined,
): Array<{ profileId: string }> => {
  return [
    ...(myProfilesData?.listMyProfiles || []).map((p) => ({
      profileId: p.profileId,
    })),
    ...(sharedProfilesData?.listMyShares || []).map((p) => ({
      profileId: p.profileId,
    })),
  ];
};

// Helper: Build "My Catalogs" list - includes owned catalogs + used managed catalogs
const buildMyCatalogs = (
  myOwnedCatalogs: Catalog[],
  publicCatalogs: Catalog[],
  catalogsInUse: Set<string>,
): Catalog[] => {
  const activeOwned = myOwnedCatalogs.filter((c) => c.isDeleted !== true);

  // Add managed catalogs that are in use but not owned
  const ownedIds = new Set(activeOwned.map((c) => c.catalogId));
  const usedPublicNotOwned = publicCatalogs.filter(
    (catalog) =>
      catalog.isPublic &&
      !ownedIds.has(catalog.catalogId) &&
      catalogsInUse.has(catalog.catalogId) &&
      catalog.isDeleted !== true,
  );

  return [...activeOwned, ...usedPublicNotOwned];
};

// Sub-component: Empty catalog state
interface EmptyCatalogStateProps {
  isMyTab: boolean;
}

const EmptyCatalogState: React.FC<EmptyCatalogStateProps> = ({ isMyTab }) => (
  <Paper sx={{ p: 4, textAlign: 'center' }}>
    <Typography color="text.secondary">
      {isMyTab ? 'No catalogs yet. Create your first catalog!' : 'No managed catalogs available.'}
    </Typography>
  </Paper>
);

// Sub-component: Catalog type chips
interface CatalogTypeChipsProps {
  inUse: boolean;
}

const CatalogTypeChips: React.FC<CatalogTypeChipsProps> = ({ inUse }) => (
  <Stack direction="row" spacing={1}>
    {inUse && <Chip label="In Use" size="small" color="success" variant="outlined" />}
  </Stack>
);

// Sub-component: Catalog action buttons
interface CatalogActionsProps {
  catalog: Catalog;
  isOwned: boolean;
  onEdit: (catalog: Catalog) => void;
  onDelete: (catalogId: string, catalogName: string) => void;
  onView: (catalogId: string) => void;
}

const CatalogActions: React.FC<CatalogActionsProps> = ({ catalog, isOwned, onEdit, onDelete, onView }) => {
  const handleViewClick = () => {
    localStorage.setItem('lastViewClicked', JSON.stringify({ catalogId: catalog.catalogId, timestamp: new Date().toISOString() }));
    onView(catalog.catalogId);
  };

  return (
    <Stack direction="row" spacing={1} justifyContent="flex-end">
      <Button
        size="small"
        startIcon={<VisibilityIcon />}
        onClick={handleViewClick}
        variant="text"
      >
        View
      </Button>
      {isOwned && (
        <>
          <IconButton size="small" onClick={() => onEdit(catalog)} color="primary">
            <EditIcon fontSize="small" />
          </IconButton>
          <IconButton size="small" onClick={() => onDelete(catalog.catalogId, catalog.catalogName)} color="error">
            <DeleteIcon fontSize="small" />
          </IconButton>
        </>
      )}
    </Stack>
  );
};

// Sub-component: Catalog table row
interface CatalogRowProps {
  catalog: Catalog;
  showActions: boolean;
  inUse: boolean;
  isOwned: boolean;
  onEdit: (catalog: Catalog) => void;
  onDelete: (catalogId: string, catalogName: string) => void;
  onView: (catalogId: string) => void;
}

// eslint-disable-next-line complexity
const CatalogRow: React.FC<CatalogRowProps> = ({ catalog, showActions, inUse, isOwned, onEdit, onDelete, onView }) => (
  <TableRow key={catalog.catalogId} hover>
    <TableCell>
      <Typography fontWeight="medium">{catalog.catalogName}</Typography>
    </TableCell>
    <TableCell>
      <CatalogTypeChips inUse={inUse} />
    </TableCell>
    <TableCell>{(catalog.products ?? []).length} items</TableCell>
    <TableCell>{formatDate(catalog.createdAt ?? '')}</TableCell>
    {showActions && (
      <TableCell align="right">
        <CatalogActions catalog={catalog} isOwned={isOwned} onEdit={onEdit} onDelete={onDelete} onView={onView} />
      </TableCell>
    )}
  </TableRow>
);

// Sub-component: Catalog table
interface CatalogTableProps {
  catalogs: Catalog[];
  showActionsColumn: boolean;
  catalogsInUse: Set<string>;
  myOwnedCatalogIds: Set<string>;
  onEdit: (catalog: Catalog) => void;
  onDelete: (catalogId: string, catalogName: string) => void;
  onView: (catalogId: string) => void;
}

const CatalogTable: React.FC<CatalogTableProps> = ({
  catalogs,
  showActionsColumn,
  catalogsInUse,
  myOwnedCatalogIds,
  onEdit,
  onDelete,
  onView,
}) => {
  if (catalogs.length === 0) {
    return <EmptyCatalogState isMyTab={showActionsColumn} />;
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
            <CatalogRow
              key={catalog.catalogId}
              catalog={catalog}
              showActions={showActionsColumn}
              inUse={catalogsInUse.has(catalog.catalogId)}
              isOwned={myOwnedCatalogIds.has(catalog.catalogId)}
              onEdit={onEdit}
              onDelete={onDelete}
              onView={onView}
            />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

// Custom hook: Fetch catalogs in use by campaigns
function useCatalogsInUse(allUserProfiles: Array<{ profileId: string }>): Set<string> {
  const [catalogsInUse, setCatalogsInUse] = useState<Set<string>>(new Set());

  const [fetchCampaigns] = useLazyQuery<{
    listCampaignsByProfile: Array<{ catalogId: string }>;
  }>(LIST_CAMPAIGNS_BY_PROFILE);

  useEffect(() => {
    if (allUserProfiles.length === 0) return;

    let isActive = true;

    const fetchAllCampaigns = async () => {
      const catalogIds = new Set<string>();
      for (const profile of allUserProfiles) {
        if (!isActive) return;

        try {
          await fetchCampaignsForProfile(profile, fetchCampaigns, catalogIds);
        } catch (error) {
          // fetchCampaignsForProfile already logs; swallow here to avoid unhandled rejections
          if (error instanceof Error && error.name === 'AbortError') {
            // ignore aborts triggered by unmount or query cancellation
            continue;
          }
          throw error;
        }
      }
      if (isActive) {
        setCatalogsInUse(catalogIds);
      }
    };

    fetchAllCampaigns();

    return () => {
      isActive = false;
    };
  }, [allUserProfiles, fetchCampaigns]);

  return catalogsInUse;
}

// Custom hook: Catalog mutations
interface CatalogMutations {
  createCatalog: ReturnType<typeof useMutation>[0];
  updateCatalog: ReturnType<typeof useMutation>[0];
  deleteCatalog: ReturnType<typeof useMutation>[0];
}

function useCatalogMutations(refetchAll: () => void): CatalogMutations {
  const [createCatalog] = useMutation(CREATE_CATALOG, {
    onCompleted: refetchAll,
  });
  const [updateCatalog] = useMutation(UPDATE_CATALOG, {
    onCompleted: refetchAll,
  });
  const [deleteCatalog] = useMutation(DELETE_CATALOG, {
    onCompleted: refetchAll,
  });

  return { createCatalog, updateCatalog, deleteCatalog };
}

// Helper: Extract catalogs from query data
// Only include truly managed (admin-maintained) catalogs in the Managed tab
function extractCatalogs(data: { listManagedCatalogs: Catalog[] } | undefined): Catalog[] {
  const catalogs = data?.listManagedCatalogs || [];
  return catalogs.filter((c) => c.catalogType === 'ADMIN_MANAGED');
}

function extractMyCatalogs(data: { listMyCatalogs: Catalog[] } | undefined): Catalog[] {
  return data?.listMyCatalogs || [];
}

// Helper: Combine loading states
function computeLoadingState(publicLoading: boolean, myLoading: boolean): boolean {
  return publicLoading || myLoading;
}

// Helper: Extract first error message
function extractErrorMessage(publicError: Error | undefined, myError: Error | undefined): string | undefined {
  return publicError?.message || myError?.message;
}

// Custom hook: Fetch public and user catalogs
interface CatalogQueries {
  publicCatalogs: Catalog[];
  myOwnedCatalogs: Catalog[];
  isLoading: boolean;
  errorMessage: string | undefined;
  refetchAll: () => void;
}

function useCatalogQueries(): CatalogQueries {
  const {
    data: publicData,
    loading: publicLoading,
    error: publicError,
    refetch: refetchPublic,
  } = useQuery<{ listManagedCatalogs: Catalog[] }>(LIST_MANAGED_CATALOGS);

  const {
    data: myData,
    loading: myLoading,
    error: myError,
    refetch: refetchMy,
  } = useQuery<{ listMyCatalogs: Catalog[] }>(LIST_MY_CATALOGS);

  const refetchAll = () => {
    refetchPublic();
    refetchMy();
  };

  return {
    publicCatalogs: extractCatalogs(publicData),
    myOwnedCatalogs: extractMyCatalogs(myData),
    isLoading: computeLoadingState(publicLoading, myLoading),
    errorMessage: extractErrorMessage(publicError, myError),
    refetchAll,
  };
}

// Custom hook: Fetch all user profiles (owned + shared)
function useAllUserProfiles(): Array<{ profileId: string }> {
  const { data: myProfilesData } = useQuery<{
    listMyProfiles: Array<{ profileId: string }>;
  }>(LIST_MY_PROFILES);

  const { data: sharedProfilesData } = useQuery<{
    listMyShares: { profileId: string; permissions: string[] }[];
  }>(LIST_MY_SHARES);

  return useMemo(() => mergeProfiles(myProfilesData, sharedProfilesData), [myProfilesData, sharedProfilesData]);
}

// Data returned by useCatalogsPageData
interface CatalogsPageData {
  publicCatalogs: Catalog[];
  myCatalogs: Catalog[];
  myOwnedCatalogIds: Set<string>;
  catalogsInUse: Set<string>;
  isLoading: boolean;
  errorMessage: string | undefined;
  mutations: CatalogMutations;
}

// Custom hook: All data fetching for CatalogsPage
function useCatalogsPageData(): CatalogsPageData {
  const { publicCatalogs, myOwnedCatalogs, isLoading, errorMessage, refetchAll } = useCatalogQueries();

  const allUserProfiles = useAllUserProfiles();
  const catalogsInUse = useCatalogsInUse(allUserProfiles);
  const mutations = useCatalogMutations(refetchAll);
  const myCatalogs = buildMyCatalogs(myOwnedCatalogs, publicCatalogs, catalogsInUse);
  const myOwnedCatalogIds = new Set(myOwnedCatalogs.map((c) => c.catalogId));

  return {
    publicCatalogs,
    myCatalogs,
    myOwnedCatalogIds,
    catalogsInUse,
    isLoading,
    errorMessage,
    mutations,
  };
}

// Sub-component: Loading state
const CatalogsLoading: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="200px">
    <CircularProgress />
  </Box>
);

// Sub-component: Error state
interface CatalogsErrorProps {
  message: string;
}

const CatalogsError: React.FC<CatalogsErrorProps> = ({ message }) => (
  <Alert severity="error">Failed to load catalogs: {message}</Alert>
);

// Sub-component: Main content (tabs + table)
interface CatalogsContentProps {
  currentTab: number;
  onTabChange: (tab: number) => void;
  myCatalogs: Catalog[];
  publicCatalogs: Catalog[];
  catalogsInUse: Set<string>;
  myOwnedCatalogIds: Set<string>;
  onEdit: (catalog: Catalog) => void;
  onDelete: (catalogId: string, catalogName: string) => void;
  onCreateCatalog: () => void;
  onView: (catalogId: string) => void;
}

const CatalogsContent: React.FC<CatalogsContentProps> = ({
  currentTab,
  onTabChange,
  myCatalogs,
  publicCatalogs,
  catalogsInUse,
  myOwnedCatalogIds,
  onEdit,
  onDelete,
  onCreateCatalog,
  onView,
}) => {
  const catalogTableProps = {
    myOwnedCatalogIds,
    onEdit,
    onDelete,
    onView,
  };

  return (
    <Box>
      <CatalogsHeader onCreateCatalog={onCreateCatalog} />
      <CatalogsInfoAlert />
      <CatalogsTabs currentTab={currentTab} onTabChange={onTabChange} />

      {currentTab === 0 && (
        <CatalogTable
          catalogs={myCatalogs}
          showActionsColumn={true}
          catalogsInUse={catalogsInUse}
          {...catalogTableProps}
        />
      )}
      {currentTab === 1 && (
        <CatalogTable
          catalogs={publicCatalogs}
          showActionsColumn={true}
          catalogsInUse={catalogsInUse}
          {...catalogTableProps}
        />
      )}
    </Box>
  );
};

export const CatalogsPage: React.FC = () => {
  const navigate = useNavigate();
  const [currentTab, setCurrentTab] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingCatalog, setEditingCatalog] = useState<Catalog | null>(null);

  const { publicCatalogs, myCatalogs, myOwnedCatalogIds, catalogsInUse, isLoading, errorMessage, mutations } =
    useCatalogsPageData();

  const handleCreateCatalog = () => {
    setEditingCatalog(null);
    setEditorOpen(true);
  };

  const handleEditCatalog = (catalog: Catalog) => {
    setEditingCatalog(catalog);
    setEditorOpen(true);
  };

  const handleDeleteCatalog = async (catalogId: string, catalogName: string) => {
    const confirmed = confirm(`Are you sure you want to delete "${catalogName}"? This action cannot be undone.`);
    if (!confirmed) return;
    await mutations.deleteCatalog({ variables: { catalogId } });
  };

  const handleViewCatalog = (catalogId: string) => {
    // Strip CATALOG# prefix for URL - will be re-added in preview page
    const catalogUuid = catalogId.replace(/^CATALOG#/, '');
    navigate(`/catalogs/${catalogUuid}/preview`);
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
    await saveCatalog(catalogData, editingCatalog, mutations);
  };

  if (isLoading) {
    return <CatalogsLoading />;
  }

  if (errorMessage) {
    return <CatalogsError message={errorMessage} />;
  }

  return (
    <>
      <CatalogsContent
        currentTab={currentTab}
        onTabChange={setCurrentTab}
        myCatalogs={myCatalogs}
        publicCatalogs={publicCatalogs}
        catalogsInUse={catalogsInUse}
        myOwnedCatalogIds={myOwnedCatalogIds}
        onEdit={handleEditCatalog}
        onDelete={handleDeleteCatalog}
        onCreateCatalog={handleCreateCatalog}
        onView={handleViewCatalog}
      />
      <CatalogEditorDialog
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSave={handleSaveCatalog}
        initialCatalog={editingCatalog}
      />
    </>
  );
};

// Helper: Save (create or update) a catalog
async function saveCatalog(
  catalogData: {
    catalogName: string;
    isPublic: boolean;
    products: Array<{
      productName: string;
      description?: string;
      price: number;
    }>;
  },
  editingCatalog: Catalog | null,
  mutations: CatalogMutations,
): Promise<void> {
  if (editingCatalog) {
    await mutations.updateCatalog({
      variables: { catalogId: editingCatalog.catalogId, input: catalogData },
    });
  } else {
    await mutations.createCatalog({ variables: { input: catalogData } });
  }
}

// Helper: Fetch campaigns for a single profile
async function fetchCampaignsForProfile(
  profile: { profileId: string },
  fetchCampaigns: ReturnType<
    typeof useLazyQuery<{
      listCampaignsByProfile: Array<{ catalogId: string }>;
    }>
  >[0],
  catalogIds: Set<string>,
): Promise<void> {
  if (!profile.profileId) return;

  try {
    const { data } = await fetchCampaigns({
      variables: { profileId: ensureProfileId(profile.profileId) },
    });
    data?.listCampaignsByProfile.forEach((campaign) => {
      if (campaign.catalogId) {
        catalogIds.add(campaign.catalogId);
      }
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      // Ignore aborted requests (e.g., component unmount or query cancellation)
      return;
    }
    console.error(`Failed to fetch campaigns for profile ${profile.profileId}:`, error);
  }
}

// Sub-component: Page header with title and create button
interface CatalogsHeaderProps {
  onCreateCatalog: () => void;
}

const CatalogsHeader: React.FC<CatalogsHeaderProps> = ({ onCreateCatalog }) => (
  <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
    <Typography variant="h4">Product Catalogs</Typography>
    <Button variant="contained" startIcon={<AddIcon />} onClick={onCreateCatalog}>
      New Catalog
    </Button>
  </Stack>
);

// Sub-component: Info alert explaining catalog types
const CatalogsInfoAlert: React.FC = () => (
  <Alert severity="info" sx={{ mb: 3 }}>
    <Typography variant="body2">
      <strong>Managed catalogs</strong> are admin-maintained catalogs visible to all users.
      <strong> Private catalogs</strong> are only visible to you and can be used for your owned tracking and use in shared campaigns.
    </Typography>
  </Alert>
);

// Sub-component: Tabs for switching between My Catalogs and Managed Catalogs
interface CatalogsTabsProps {
  currentTab: number;
  onTabChange: (newTab: number) => void;
}

const CatalogsTabs: React.FC<CatalogsTabsProps> = ({ currentTab, onTabChange }) => (
  <Paper sx={{ mb: 3 }}>
    <Tabs value={currentTab} onChange={(_, newValue) => onTabChange(newValue)} variant="fullWidth">
      <Tab label="My Catalogs" />
      <Tab label="Managed Catalogs" />
    </Tabs>
  </Paper>
);
