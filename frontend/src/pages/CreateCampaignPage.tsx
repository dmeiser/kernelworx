/**
 * CreateCampaignPage component - Page for creating a new sales campaign
 *
 * Supports two modes:
 * 1. Shared Campaign mode: Accessed via /c/:sharedCampaignCode - all fields locked except profile selection
 * 2. Manual mode: Accessed via /create-campaign - all fields editable with optional unit info
 */

import React from "react";
import { useParams } from "react-router-dom";
import { Box, Typography } from "@mui/material";
import { useCreateCampaignPageSetup } from "../hooks/useCreateCampaignPageSetup";
import {
  LoadingState,
  CampaignNotFoundError,
  CampaignErrorState,
  SharedCampaignBanner,
  DiscoveredCampaignAlert,
} from "./CreateCampaignPageComponents";
import { CampaignForm } from "./CampaignForm";

const getLoadingView = (sharedCampaignLoading: boolean) => {
  if (sharedCampaignLoading) return <LoadingState />;
  return null;
};

const getInactiveView = (
  sharedCampaignInactive: boolean,
  navigate: (path: string) => void,
) => {
  if (!sharedCampaignInactive) return null;
  return <CampaignNotFoundError onReturnClick={() => navigate("/scouts")} />;
};

const getErrorView = (
  sharedCampaignError: unknown,
  navigate: (path: string) => void,
) => {
  if (!sharedCampaignError) return null;
  return (
    <CampaignErrorState
      error={sharedCampaignError}
      onReturnClick={() => navigate("/scouts")}
    />
  );
};

const getGuardView = (
  sharedCampaignLoading: boolean,
  sharedCampaignInactive: boolean,
  sharedCampaignError: unknown,
  navigate: (path: string) => void,
) => {
  const loadingView = getLoadingView(sharedCampaignLoading);
  if (loadingView) return loadingView;

  const inactiveView = getInactiveView(sharedCampaignInactive, navigate);
  if (inactiveView) return inactiveView;

  const errorView = getErrorView(sharedCampaignError, navigate);
  if (errorView) return errorView;

  return null;
};

const SharedBannerSection: React.FC<{
  setup: ReturnType<typeof useCreateCampaignPageSetup>;
}> = ({ setup }) => {
  if (!(setup.isSharedCampaignMode && setup.sharedCampaign)) return null;
  return <SharedCampaignBanner sharedCampaign={setup.sharedCampaign} />;
};

const DiscoveredAlertSection: React.FC<{
  setup: ReturnType<typeof useCreateCampaignPageSetup>;
  hasDiscoveredCampaigns: boolean;
  onUseCampaign: (code: string) => void;
}> = ({ setup, hasDiscoveredCampaigns, onUseCampaign }) => {
  if (!hasDiscoveredCampaigns) return null;
  const first = setup.discoveredSharedCampaigns[0];
  return (
    <DiscoveredCampaignAlert
      campaignName={setup.formState.campaignName}
      campaignYear={setup.formState.campaignYear}
      unitType={setup.formState.unitType}
      unitNumber={setup.formState.unitNumber}
      city={setup.formState.city}
      state={setup.formState.state}
      createdByName={first.createdByName}
      onUseCampaign={() => onUseCampaign(first.sharedCampaignCode)}
    />
  );
};

const getCampaignFlags = (
  setup: ReturnType<typeof useCreateCampaignPageSetup>,
) => {
  const hasSharedCode = Boolean(setup.effectiveSharedCampaignCode);
  return {
    sharedCampaignLoading: hasSharedCode && setup.sharedCampaignLoading,
    sharedCampaignInactive:
      hasSharedCode &&
      (!setup.sharedCampaign || !setup.sharedCampaign.isActive),
    hasDiscoveredCampaigns:
      !setup.isSharedCampaignMode && setup.discoveredSharedCampaigns.length > 0,
  };
};

const CreateCampaignPageView: React.FC<{
  setup: ReturnType<typeof useCreateCampaignPageSetup>;
}> = ({ setup }) => {
  const {
    sharedCampaignLoading,
    sharedCampaignInactive,
    hasDiscoveredCampaigns,
  } = getCampaignFlags(setup);

  const handleUseSharedCampaign = (code: string) => {
    setup.navigate(`/c/${code}`);
  };

  const handleSubmitClick = async () => {
    await setup.handleSubmit({
      isSharedCampaignMode: setup.isSharedCampaignMode,
      effectiveSharedCampaignCode: setup.effectiveSharedCampaignCode,
      sharedCampaignCreatedByName: setup.sharedCampaign?.createdByName,
    });
  };

  const guardView = getGuardView(
    sharedCampaignLoading,
    sharedCampaignInactive,
    setup.sharedCampaignError,
    setup.navigate,
  );
  if (guardView) return guardView;

  return (
    <Box maxWidth="md" mx="auto" p={3}>
      <Typography variant="h4" gutterBottom>
        Create New Campaign
      </Typography>

      <SharedBannerSection setup={setup} />

      <DiscoveredAlertSection
        setup={setup}
        hasDiscoveredCampaigns={hasDiscoveredCampaigns}
        onUseCampaign={handleUseSharedCampaign}
      />

      <CampaignForm
        formState={setup.formState}
        profiles={setup.profiles}
        profilesLoading={setup.profilesLoading}
        isSharedCampaignMode={setup.isSharedCampaignMode}
        sharedCampaign={setup.sharedCampaign}
        filteredMyCatalogs={setup.filteredMyCatalogs}
        filteredPublicCatalogs={setup.filteredPublicCatalogs}
        catalogsLoading={setup.catalogsLoading}
        isFormValid={setup.isFormValid}
        onSubmit={handleSubmitClick}
        onCancel={() => setup.navigate("/scouts")}
      />
    </Box>
  );
};

export const CreateCampaignPage: React.FC = () => {
  const { sharedCampaignCode } = useParams<{ sharedCampaignCode: string }>();
  const setup = useCreateCampaignPageSetup(sharedCampaignCode);
  return <CreateCampaignPageView setup={setup} />;
};
