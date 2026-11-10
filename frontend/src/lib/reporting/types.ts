/**
 * Shared types for the browser-only reporting engine.
 *
 * Architecture: docs/specs/show_sell/BROWSER_REPORTING_ARCHITECTURE.md —
 * the browser assembles reports from authorized paginated GraphQL data.
 * The server never generates reports, files, or documents.
 */

/** One scope a report is generated for. */
export interface ReportScope {
  unitId: string;
  unitCampaignId: string;
  /** Present for event-scoped reports. */
  showAndSellId?: string;
  /** Human-readable scope labels rendered into every output. */
  labels: {
    unitName: string;
    unitCampaignName: string;
    showAndSellLabel?: string;
  };
}

/** The wire shape of one paginated query result the loader accepts. */
export interface PageFetchResult<Row> {
  items: Row[];
  nextToken?: string | null;
}

/** Fetches one page. `nextToken` is null for the first page. */
export type PageFetcher<Row> = (nextToken: string | null) => Promise<PageFetchResult<Row>>;

export interface LoadProgress {
  pagesCompleted: number;
  itemsLoaded: number;
}

/** Cooperative cancellation; the UI wires this to a Cancel button. */
export interface CancellationToken {
  readonly cancelled: boolean;
  throwIfCancelled(): void;
}

/**
 * A fully-assembled, version-stable dataset ready for assembler/writer
 * consumption. Rows come from one or more followed queries inside one
 * scope; `sourceVersions` pins every source's version at assembly time.
 */
export interface ReportDataset<Row> {
  scope: ReportScope;
  /** Generation timestamp (ISO 8601) rendered into every output. */
  generatedAt: string;
  /** Source name -> version observed at assembly (balance/finalization/etc.). */
  sourceVersions: Record<string, number | string>;
  rows: Row[];
}

/** A named paginated source contributing rows to a dataset. */
export interface ReportSource<Row> {
  /** Stable key recorded in `sourceVersions`. */
  key: string;
  fetcher: PageFetcher<Row>;
  /**
   * Reads this source's version from a fetched page, when the API
   * provides one. Used for version-stability validation across pages.
   */
  readVersion?: (page: PageFetchResult<Row>) => number | string | undefined;
}
