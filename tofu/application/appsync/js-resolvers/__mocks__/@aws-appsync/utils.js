export const util = {
  dynamodb: {
    toMapValues: (obj) => obj,
  },
  time: {
    nowISO8601: () => '2024-01-01T00:00:00Z',
    nowEpochSeconds: () => 1704067200,
    epochMilliSecondsToISO8601: (ms) => new Date(ms).toISOString(),
    parseISO8601ToEpochMilliSeconds: (str) => {
      if (typeof str !== 'string') return null;
      let s = str;
      if (!s.endsWith('Z') && !s.includes('+') && s.lastIndexOf('-') <= 10) {
        s = s + 'Z';
      }
      const ms = Date.parse(s);
      return isNaN(ms) ? null : ms;
    },
  },
  autoId: () => 'auto-generated-id',
  error: (message, type, data, errorInfo) => {
    const error = new Error(`${type}: ${message}`);
    // #329: AppSync merges the 4th util.error arg into GraphQL extensions.
    error.errorInfo = errorInfo;
    throw error;
  },
};

export const runtime = {
  earlyReturn: (value) => value,
};

