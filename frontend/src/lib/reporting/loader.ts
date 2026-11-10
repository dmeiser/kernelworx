/**
 * Dataset loader for the browser-only reporting engine.
 *
 * Contract (BROWSER_REPORTING_ARCHITECTURE.md §5):
 * - follow EVERY page required for the selected scope, or fail visibly;
 * - never silently truncate a report;
 * - if source versions change during assembly, fail and let the UI offer
 *   a refresh rather than mixing versions silently.
 */

import type {
  CancellationToken,
  LoadProgress,
  PageFetchResult,
  PageFetcher,
  ReportDataset,
  ReportScope,
  ReportSource,
} from './types';

/** Raised when a page is structurally incomplete. */
export class IncompletePageError extends Error {
  constructor(sourceKey: string) {
    super(`Report source "${sourceKey}" returned an incomplete page; the report cannot be generated.`);
    this.name = 'IncompletePageError';
  }
}

/** Raised when a source's version changes mid-assembly. */
export class VersionDriftError extends Error {
  constructor(sourceKey: string) {
    super(
      `Report source "${sourceKey}" changed while the report was being assembled. ` +
        'Refresh the data and generate the report again rather than mixing versions.',
    );
    this.name = 'VersionDriftError';
  }
}

/** Raised on cooperative cancellation. */
export class LoadCancelledError extends Error {
  constructor() {
    super('Report data load was cancelled.');
    this.name = 'LoadCancelledError';
  }
}

/** Raised when a dataset grows past the interactive-report ceiling. */
export class ReportTooLargeError extends Error {
  constructor(sourceKey: string, maxPages: number) {
    super(
      `Report source "${sourceKey}" exceeded ${maxPages} pages. Narrow the report ` +
        'filters (shorter time window or smaller scope) and generate again.',
    );
    this.name = 'ReportTooLargeError';
  }
}

export const DEFAULT_MAX_PAGES = 200;

/**
 * Follows every page of one paginated source. Fails loudly on incomplete
 * pages, version drift, cancellation, or the page ceiling — a failed or
 * forbidden page fails the whole report.
 */
interface PageLoopState<Row> {
  rows: Row[];
  nextToken: string | null;
  pagesCompleted: number;
  version: number | string | undefined;
}

async function fetchValidatedPage<Row>(
  fetcher: PageFetcher<Row>,
  nextToken: string | null,
  sourceKey: string,
): Promise<PageFetchResult<Row>> {
  const page = await fetcher(nextToken);
  if (!page || !Array.isArray(page.items)) {
    throw new IncompletePageError(sourceKey);
  }
  return page;
}

function applyPage<Row>(
  state: PageLoopState<Row>,
  page: PageFetchResult<Row>,
  options: {
    sourceKey: string;
    onProgress?: (progress: LoadProgress) => void;
    maxPages?: number;
  },
): void {
  state.rows.push(...page.items);
  state.pagesCompleted += 1;
  const maxPages = options.maxPages ?? DEFAULT_MAX_PAGES;
  if (state.pagesCompleted > maxPages) {
    throw new ReportTooLargeError(options.sourceKey, maxPages);
  }
  options.onProgress?.({ pagesCompleted: state.pagesCompleted, itemsLoaded: state.rows.length });
}

async function runPages<Row>(
  fetcher: PageFetcher<Row>,
  options: {
    sourceKey: string;
    onProgress?: (progress: LoadProgress) => void;
    token?: CancellationToken;
    readVersion?: (page: PageFetchResult<Row>) => number | string | undefined;
    maxPages?: number;
  },
  state: PageLoopState<Row>,
): Promise<void> {
  options.token?.throwIfCancelled();
  const page = await fetchValidatedPage(fetcher, state.nextToken, options.sourceKey);
  options.token?.throwIfCancelled();
  state.version = trackVersion(options.sourceKey, state.version, page, options.readVersion);
  applyPage(state, page, options);
  state.nextToken = page.nextToken ?? null;
  if (state.nextToken !== null) {
    await runPages(fetcher, options, state);
  }
}

export async function followAllPages<Row>(
  fetcher: PageFetcher<Row>,
  options: {
    sourceKey: string;
    onProgress?: (progress: LoadProgress) => void;
    token?: CancellationToken;
    readVersion?: (page: PageFetchResult<Row>) => number | string | undefined;
    maxPages?: number;
  },
): Promise<{ rows: Row[]; version: number | string | undefined }> {
  const state: PageLoopState<Row> = { rows: [], nextToken: null, pagesCompleted: 0, version: undefined };
  await runPages(fetcher, options, state);
  return { rows: state.rows, version: state.version };
}

function trackVersion<Row>(
  sourceKey: string,
  version: number | string | undefined,
  page: PageFetchResult<Row>,
  readVersion?: (page: PageFetchResult<Row>) => number | string | undefined,
): number | string | undefined {
  const pageVersion = readVersion ? readVersion(page) : undefined;
  if (pageVersion === undefined) {
    return version;
  }
  if (version === undefined) {
    return pageVersion;
  }
  if (pageVersion !== version) {
    throw new VersionDriftError(sourceKey);
  }
  return version;
}

/** Simple manual token for UIs without an AbortController wrapper. */
export function createCancellationToken(): CancellationToken & { cancel(): void } {
  let cancelled = false;
  return {
    get cancelled() {
      return cancelled;
    },
    cancel() {
      cancelled = true;
    },
    throwIfCancelled() {
      if (cancelled) throw new LoadCancelledError();
    },
  };
}

/**
 * Loads a full multi-source dataset for one scope. Every source is
 * followed to completion (or the whole load fails); source versions are
 * pinned into the returned dataset.
 */
export async function loadReportDataset<Row>(
  scope: ReportScope,
  sources: ReadonlyArray<ReportSource<Row>>,
  options: {
    onProgress?: (sourceKey: string, progress: LoadProgress) => void;
    token?: CancellationToken;
    maxPages?: number;
    now?: () => Date;
  } = {},
): Promise<ReportDataset<Row>> {
  const rows: Row[] = [];
  const sourceVersions: Record<string, number | string> = {};
  for (const source of sources) {
    const result = await followAllPages(source.fetcher, {
      sourceKey: source.key,
      onProgress: (p) => options.onProgress?.(source.key, p),
      token: options.token,
      readVersion: source.readVersion,
      maxPages: options.maxPages,
    });
    rows.push(...result.rows);
    if (result.version !== undefined) {
      sourceVersions[source.key] = result.version;
    }
  }
  return {
    scope,
    generatedAt: (options.now ?? (() => new Date()))().toISOString(),
    sourceVersions,
    rows,
  };
}
