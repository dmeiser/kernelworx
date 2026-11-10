/**
 * Tests for the reporting-engine loader.
 */

import { describe, it, expect } from 'vitest';
import {
  DEFAULT_MAX_PAGES,
  IncompletePageError,
  LoadCancelledError,
  ReportTooLargeError,
  VersionDriftError,
  createCancellationToken,
  followAllPages,
  loadReportDataset,
} from './loader';
import type { PageFetchResult, ReportScope } from './types';

function paged<T>(pages: Array<PageFetchResult<T>>) {
  const calls: Array<string | null> = [];
  const fetcher = async (nextToken: string | null) => {
    calls.push(nextToken);
    const index = calls.length - 1;
    if (index >= pages.length) throw new Error(`unexpected extra fetch (token=${nextToken})`);
    return pages[index];
  };
  return { fetcher, calls };
}

describe('followAllPages', () => {
  it('follows every page until the cursor ends', async () => {
    const { fetcher, calls } = paged([
      { items: ['a', 'b'], nextToken: 't2' },
      { items: ['c'], nextToken: null },
    ]);
    const result = await followAllPages(fetcher, { sourceKey: 'sales' });
    expect(result.rows).toEqual(['a', 'b', 'c']);
    expect(calls).toEqual([null, 't2']);
    expect(result.version).toBeUndefined();
  });

  it('fails visibly on an incomplete page', async () => {
    const { fetcher } = paged([{ items: undefined as unknown as string[], nextToken: null }]);
    await expect(followAllPages(fetcher, { sourceKey: 'sales' })).rejects.toBeInstanceOf(IncompletePageError);
  });

  it('never silently truncates: page ceiling throws with guidance', async () => {
    // Endless cursor: without a ceiling this loop would never finish.
    const endless = async () => ({ items: ['x'], nextToken: 'more' });
    await expect(followAllPages(endless, { sourceKey: 'sales', maxPages: 2 })).rejects.toBeInstanceOf(
      ReportTooLargeError,
    );
  });

  it('default ceiling is generous but finite', () => {
    expect(DEFAULT_MAX_PAGES).toBeGreaterThan(100);
  });

  it('detects version drift across pages and fails', async () => {
    const { fetcher } = paged([
      { items: ['a'], nextToken: 't2' },
      { items: ['b'], nextToken: null },
    ]);
    const readVersion = (page: PageFetchResult<string>) => (page.items[0] === 'a' ? 1 : 2);
    await expect(followAllPages(fetcher, { sourceKey: 'inventory', readVersion })).rejects.toBeInstanceOf(
      VersionDriftError,
    );
  });

  it('passes stable versions through to the result', async () => {
    const { fetcher } = paged([
      { items: ['a'], nextToken: 't2' },
      { items: ['b'], nextToken: null },
    ]);
    const result = await followAllPages(fetcher, { sourceKey: 'inventory', readVersion: () => 7 });
    expect(result.version).toBe(7);
  });

  it('supports cooperative cancellation between pages', async () => {
    const { fetcher } = paged([{ items: ['a'], nextToken: 't2' }]);
    const token = createCancellationToken();
    token.cancel();
    await expect(followAllPages(fetcher, { sourceKey: 'sales', token })).rejects.toBeInstanceOf(LoadCancelledError);
  });

  it('reports progress per page', async () => {
    const { fetcher } = paged([
      { items: ['a'], nextToken: 't2' },
      { items: ['b', 'c'], nextToken: null },
    ]);
    const progress: Array<{ pagesCompleted: number; itemsLoaded: number }> = [];
    await followAllPages(fetcher, { sourceKey: 'sales', onProgress: (p) => progress.push(p) });
    expect(progress).toEqual([
      { pagesCompleted: 1, itemsLoaded: 1 },
      { pagesCompleted: 2, itemsLoaded: 3 },
    ]);
  });
});

describe('loadReportDataset', () => {
  const scope: ReportScope = {
    unitId: 'unit-1',
    unitCampaignId: 'uc-1',
    labels: { unitName: 'Troop 1', unitCampaignName: 'Fall 2026' },
  };

  it('assembles a multi-source dataset with pinned versions and a generation stamp', async () => {
    const dataset = await loadReportDataset(scope, [
      { key: 'sales', fetcher: async () => ({ items: ['s1'], nextToken: null }) },
      { key: 'weowe', fetcher: async () => ({ items: ['w1'], nextToken: null }), readVersion: () => 4 },
    ]);
    expect(dataset.rows).toEqual(['s1', 'w1']);
    expect(dataset.sourceVersions).toEqual({ weowe: 4 });
    expect(dataset.generatedAt).toBeTruthy();
    expect(dataset.scope).toEqual(scope);
  });

  it('a failed source fails the whole dataset', async () => {
    await expect(
      loadReportDataset(scope, [
        { key: 'ok', fetcher: async () => ({ items: ['a'], nextToken: null }) },
        {
          key: 'forbidden',
          fetcher: async () => {
            throw new Error('FORBIDDEN');
          },
        },
      ]),
    ).rejects.toThrow('FORBIDDEN');
  });

  it('honors a fixed clock for deterministic generation stamps', async () => {
    const fixed = new Date('2026-11-10T12:00:00Z');
    const dataset = await loadReportDataset(
      scope,
      [{ key: 'sales', fetcher: async () => ({ items: [], nextToken: null }) }],
      { now: () => fixed },
    );
    expect(dataset.generatedAt).toBe('2026-11-10T12:00:00.000Z');
  });
});
