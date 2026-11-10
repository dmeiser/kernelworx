/**
 * Dataset validator for the browser-only reporting engine.
 *
 * Rejects incomplete pages, missing required detail, and cross-scope
 * identifiers rather than silently producing a partial report.
 * Browser code is untrusted; these checks are a second line of defense
 * on top of server-side authorization — never a substitute for it.
 */

/** Raised when a row carries an identifier outside the report scope. */
export class CrossScopeRowError extends Error {
  constructor(field: string, expected: string, actual: unknown) {
    super(`Report row has ${field}="${String(actual)}" outside the report scope "${expected}".`);
    this.name = 'CrossScopeRowError';
  }
}

/** Raised when a required detail field is absent from a row. */
export class MissingDetailError extends Error {
  constructor(field: string) {
    super(`Report row is missing required detail field "${field}".`);
    this.name = 'MissingDetailError';
  }
}

/**
 * Every row that carries the checked field must match the scope value.
 * Rows without the field pass (projection-dependent); a row contradicting
 * the scope is a bug or an authorization leak and fails the report.
 */
export function assertScopeConsistency<Row extends Record<string, unknown>>(
  rows: ReadonlyArray<Row>,
  field: string,
  expected: string,
): void {
  for (const row of rows) {
    const value = row[field];
    if (value === undefined || value === null) continue;
    if (value !== expected) {
      throw new CrossScopeRowError(field, expected, value);
    }
  }
}

/** Throws on the first row missing any required field. */
export function requireFields<Row extends Record<string, unknown>>(
  rows: ReadonlyArray<Row>,
  fields: ReadonlyArray<string>,
): void {
  for (const row of rows) {
    for (const field of fields) {
      if (row[field] === undefined || row[field] === null) {
        throw new MissingDetailError(field);
      }
    }
  }
}

/**
 * Asserts a dataset's source versions match a previously observed set
 * (e.g. versions captured when the dataset was loaded). Drift means the
 * data changed between load and render/export and the UI must refresh.
 */
export function assertVersionStability(
  observed: Record<string, number | string>,
  expected: Record<string, number | string>,
): void {
  for (const key of Object.keys(expected)) {
    if (observed[key] !== undefined && observed[key] !== expected[key]) {
      throw new Error(
        `Report source "${key}" changed from version ${String(expected[key])} to ${String(
          observed[key],
        )}; refresh before generating output.`,
      );
    }
  }
}
