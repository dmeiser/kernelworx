/**
 * Custom hook for client-orchestrated account deletion.
 *
 * Sequentially deletes all seller profiles owned by the user (with cascades
 * for campaigns, orders, shares, and invites) before deleting the account
 * record and authentication credentials.
 *
 * Provides real-time status feedback for each entity and allows resuming
 * if any step fails. Catalogs are never deleted.
 */

import { useState, useCallback } from 'react';
import { useApolloClient } from '@apollo/client/react';
import { DELETE_SELLER_PROFILE, DELETE_MY_ACCOUNT } from '../lib/graphql';
import { fetchAllMyProfiles } from '../lib/myProfiles';

export type DeletionStep = 'idle' | 'discovering' | 'deleting-profiles' | 'deleting-account' | 'completed' | 'error';

export interface ProfileDeletionItem {
  profileId: string;
  sellerName: string;
  status: 'pending' | 'in-progress' | 'completed' | 'failed';
  error?: string;
}

export interface UseAccountDeletionOptions {
  onSuccess?: () => Promise<void> | void;
}

export interface UseAccountDeletionReturn {
  step: DeletionStep;
  profiles: ProfileDeletionItem[];
  error: string | null;
  isProcessing: boolean;
  isLoadingProfiles: boolean;
  isDiscovered: boolean;
  loadProfiles: () => Promise<ProfileDeletionItem[]>;
  startDeletion: () => Promise<void>;
  resumeDeletion: () => Promise<void>;
  reset: () => void;
}

function isNotFoundError(err: unknown): boolean {
  if (!err || typeof err !== 'object') {
    return false;
  }
  const message =
    'message' in err && typeof (err as { message: unknown }).message === 'string'
      ? (err as { message: string }).message.toLowerCase()
      : '';
  return message.includes('not found');
}

async function fetchProfiles(client: ReturnType<typeof useApolloClient>): Promise<ProfileDeletionItem[]> {
  const profiles = await fetchAllMyProfiles(client);
  return profiles
    .filter((item) => Boolean(item?.profileId))
    .map((item) => ({
      profileId: item.profileId,
      sellerName: item.sellerName || 'Scout Profile',
      status: 'pending' as const,
    }));
}

async function deleteSingleProfile(client: ReturnType<typeof useApolloClient>, profileId: string): Promise<void> {
  try {
    const result = await client.mutate({
      mutation: DELETE_SELLER_PROFILE,
      variables: { profileId },
    });
    if (result.error) {
      throw result.error;
    }
  } catch (err) {
    if (!isNotFoundError(err)) {
      throw err;
    }
  }
}

async function executeAccountDeletion(client: ReturnType<typeof useApolloClient>): Promise<void> {
  const result = await client.mutate({
    mutation: DELETE_MY_ACCOUNT,
  });
  if (result.error) {
    throw result.error;
  }
}

const COMPLETION_BANNER_DELAY_MS = 500;

export function useAccountDeletion(options?: UseAccountDeletionOptions): UseAccountDeletionReturn {
  const client = useApolloClient();
  const [step, setStep] = useState<DeletionStep>('idle');
  const [profiles, setProfiles] = useState<ProfileDeletionItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoadingProfiles, setIsLoadingProfiles] = useState(false);
  const [isDiscovered, setIsDiscovered] = useState(false);

  const updateProfileStatus = useCallback((index: number, patch: Partial<ProfileDeletionItem>) => {
    setProfiles((prev) => {
      const copy = [...prev];
      if (copy[index]) {
        copy[index] = { ...copy[index], ...patch };
      }
      return copy;
    });
  }, []);

  const loadProfiles = useCallback(async () => {
    setIsLoadingProfiles(true);
    setError(null);
    try {
      const discovered = await fetchProfiles(client);
      setProfiles(discovered);
      setIsDiscovered(true);
      setIsLoadingProfiles(false);
      return discovered;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load user profiles';
      setError(msg);
      setIsLoadingProfiles(false);
      return [];
    }
  }, [client]);

  const finalizeAccountDeletion = useCallback(async () => {
    setStep('deleting-account');
    try {
      await executeAccountDeletion(client);
      setStep('completed');
      await new Promise((resolve) => setTimeout(resolve, COMPLETION_BANNER_DELAY_MS));
      await options?.onSuccess?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to delete account';
      setError(msg);
      setStep('error');
    }
  }, [client, options]);

  const runProfileDeletionLoop = useCallback(
    async (currentProfiles: ProfileDeletionItem[], startIndex: number) => {
      for (let i = startIndex; i < currentProfiles.length; i++) {
        const item = currentProfiles[i];
        if (item.status === 'completed') {
          continue;
        }

        updateProfileStatus(i, { status: 'in-progress', error: undefined });
        try {
          await deleteSingleProfile(client, item.profileId);
          updateProfileStatus(i, { status: 'completed' });
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Failed to delete profile';
          updateProfileStatus(i, { status: 'failed', error: msg });
          setError(msg);
          setStep('error');
          return;
        }
      }

      await finalizeAccountDeletion();
    },
    [client, finalizeAccountDeletion, updateProfileStatus],
  );

  const discoverProfiles = useCallback(async () => {
    setStep('discovering');
    try {
      const discovered = await fetchProfiles(client);
      setProfiles(discovered);
      setIsDiscovered(true);
      return discovered;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load user profiles';
      setError(msg);
      setStep('error');
      return null;
    }
  }, [client]);

  const startDeletion = useCallback(async () => {
    setError(null);
    let current = profiles;

    if (!isDiscovered) {
      const discovered = await discoverProfiles();
      if (discovered === null) {
        return;
      }
      current = discovered;
    }

    setStep('deleting-profiles');
    await runProfileDeletionLoop(current, 0);
  }, [discoverProfiles, isDiscovered, profiles, runProfileDeletionLoop]);

  const resumeDeletion = useCallback(async () => {
    setError(null);

    if (!isDiscovered) {
      const discovered = await discoverProfiles();
      if (discovered === null) {
        return;
      }
      setStep('deleting-profiles');
      await runProfileDeletionLoop(discovered, 0);
      return;
    }

    const firstUnfinished = profiles.findIndex((p) => p.status !== 'completed');
    if (firstUnfinished !== -1) {
      setStep('deleting-profiles');
      await runProfileDeletionLoop(profiles, 0);
      return;
    }

    await finalizeAccountDeletion();
  }, [discoverProfiles, finalizeAccountDeletion, isDiscovered, profiles, runProfileDeletionLoop]);

  const reset = useCallback(() => {
    setStep('idle');
    setProfiles([]);
    setError(null);
    setIsLoadingProfiles(false);
    setIsDiscovered(false);
  }, []);

  const isProcessing = step === 'discovering' || step === 'deleting-profiles' || step === 'deleting-account';

  return {
    step,
    profiles,
    error,
    isProcessing,
    isLoadingProfiles,
    isDiscovered,
    loadProfiles,
    startDeletion,
    resumeDeletion,
    reset,
  };
}
