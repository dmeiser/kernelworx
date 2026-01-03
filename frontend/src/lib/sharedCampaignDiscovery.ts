export let SHARED_DISCOVERY_DEBOUNCE_MS = 500;

export const setDiscoveryDebounceMs = (ms: number) => {
  SHARED_DISCOVERY_DEBOUNCE_MS = ms;
};
