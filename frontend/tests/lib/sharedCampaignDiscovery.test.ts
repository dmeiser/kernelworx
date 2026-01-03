import { describe, it, expect } from 'vitest';
import { SHARED_DISCOVERY_DEBOUNCE_MS, setDiscoveryDebounceMs } from '../../src/lib/sharedCampaignDiscovery';

describe('sharedCampaignDiscovery', () => {
  it('has default debounce value of 500ms', () => {
    // Reset to default first
    setDiscoveryDebounceMs(500);
    expect(SHARED_DISCOVERY_DEBOUNCE_MS).toBe(500);
  });

  it('allows setting custom debounce value', () => {
    setDiscoveryDebounceMs(100);
    expect(SHARED_DISCOVERY_DEBOUNCE_MS).toBe(100);

    // Reset to default
    setDiscoveryDebounceMs(500);
  });
});
