/**
 * Custom hook for refetch profiles effect
 */
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

export const useProfileRefetch = (refetchProfiles: () => void) => {
  const location = useLocation();

  useEffect(() => {
    if (location.state?.fromProfileCreation) {
      refetchProfiles();
    }
  }, [location.state, refetchProfiles]);
};
