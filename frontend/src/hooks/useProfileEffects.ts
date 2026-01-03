/**
 * Custom hook for profile effects (auto-select, redirect on no profiles)
 */
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

interface SellerProfile {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
}

export const useProfileEffects = (
  profileId: string,
  setProfileId: (id: string) => void,
  profiles: SellerProfile[],
  profilesLoading: boolean,
  isSharedCampaignMode: boolean,
  effectiveSharedCampaignCode: string | undefined,
  navigate: ReturnType<typeof useNavigate>,
) => {
  // Auto-select profile if only one exists
  useEffect(() => {
    if (!profilesLoading && profiles.length === 1 && !profileId) {
      setProfileId(profiles[0].profileId);
    }
  }, [profilesLoading, profiles, profileId, setProfileId]);

  // Redirect to profile creation if user has no profiles in shared campaign mode
  useEffect(() => {
    if (isSharedCampaignMode && !profilesLoading && profiles.length === 0 && effectiveSharedCampaignCode) {
      navigate('/scouts', {
        state: {
          returnTo: `/c/${effectiveSharedCampaignCode}`,
          sharedCampaignCode: effectiveSharedCampaignCode,
          message: 'Create a scout to use this campaign link',
        },
        replace: true,
      });
    }
  }, [isSharedCampaignMode, profilesLoading, profiles.length, effectiveSharedCampaignCode, navigate]);
};
