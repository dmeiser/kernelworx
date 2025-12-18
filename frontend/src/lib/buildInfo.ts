/**
 * Build information - injected at build time by Vite
 */

export const buildInfo = {
  version: __APP_VERSION__,
  commit: __GIT_COMMIT__,
  branch: __GIT_BRANCH__,
  buildTime: __BUILD_TIME__,
};

/**
 * Check if we're in a development environment
 */
export const isDevelopment = (): boolean => {
  // Check if hostname indicates dev environment
  const hostname = typeof window !== "undefined" ? window.location.hostname : "";
  return (
    hostname === "localhost" ||
    hostname.startsWith("dev.") ||
    hostname.includes(".dev.") ||
    import.meta.env.DEV
  );
};

/**
 * Get a short version string for display
 * Format: "v0.0.0 (abc1234)"
 */
export const getVersionString = (): string => {
  return `v${buildInfo.version} (${buildInfo.commit})`;
};

/**
 * Get detailed build info for debugging
 */
export const getDetailedBuildInfo = (): string => {
  const buildDate = new Date(buildInfo.buildTime);
  return `Version: ${buildInfo.version}\nCommit: ${buildInfo.commit}\nBranch: ${buildInfo.branch}\nBuilt: ${buildDate.toLocaleString()}`;
};
