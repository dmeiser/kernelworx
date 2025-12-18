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
 * This checks the runtime hostname, not build mode
 */
export const isDevelopment = (): boolean => {
  // Always check hostname at runtime - this works regardless of build mode
  if (typeof window === "undefined") {
    return false;
  }
  
  const hostname = window.location.hostname;
  
  // Dev environments: localhost, dev.*, *.dev.*
  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return true;
  }
  if (hostname.startsWith("dev.")) {
    return true;
  }
  if (hostname.includes(".dev.")) {
    return true;
  }
  
  return false;
};

/**
 * Get build time formatted in UTC
 */
export const getBuildTimeUTC = (): string => {
  const buildDate = new Date(buildInfo.buildTime);
  return buildDate.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
};

/**
 * Get short build time (just date and time, no seconds)
 */
export const getShortBuildTime = (): string => {
  const buildDate = new Date(buildInfo.buildTime);
  return buildDate.toISOString().slice(0, 16).replace("T", " ") + " UTC";
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
  return `Version: ${buildInfo.version}\nCommit: ${buildInfo.commit}\nBranch: ${buildInfo.branch}\nBuilt: ${getBuildTimeUTC()}`;
};
