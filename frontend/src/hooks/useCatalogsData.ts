/**
 * Custom hook for managing catalog queries and filtering
 */
import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { LIST_MANAGED_CATALOGS, LIST_MY_CATALOGS } from '../lib/graphql';
import type { GqlCatalog } from '../types';

export const useCatalogsData = (isSharedCampaignMode: boolean) => {
  const { data: publicCatalogsData, loading: publicLoading } = useQuery<{
    listManagedCatalogs: GqlCatalog[];
  }>(LIST_MANAGED_CATALOGS, { skip: isSharedCampaignMode });

  const { data: myCatalogsData, loading: myLoading } = useQuery<{
    listMyCatalogs: GqlCatalog[];
  }>(LIST_MY_CATALOGS, { skip: isSharedCampaignMode });

  const { filteredPublicCatalogs, filteredMyCatalogs } = useMemo(() => {
    const publicCatalogs = publicCatalogsData?.listManagedCatalogs || [];
    const myCatalogs = myCatalogsData?.listMyCatalogs || [];
    const myIdSet = new Set(myCatalogs.map((c) => c.catalogId));
    return {
      filteredPublicCatalogs: publicCatalogs.filter((c) => !myIdSet.has(c.catalogId) && c.isDeleted !== true),
      filteredMyCatalogs: myCatalogs.filter((c) => c.isDeleted !== true),
    };
  }, [myCatalogsData, publicCatalogsData]);

  const catalogsLoading = publicLoading || myLoading;

  return {
    filteredPublicCatalogs,
    filteredMyCatalogs,
    catalogsLoading,
  };
};
