export const util = {
  dynamodb: {
    toMapValues: (obj) => obj,
  },
  time: {
    nowISO8601: () => '2024-01-01T00:00:00Z',
    nowEpochSeconds: () => 1704067200,
    epochMilliSecondsToISO8601: (ms) => new Date(ms).toISOString(),
  },
  autoId: () => 'auto-generated-id',
  error: (message, type) => {
    throw new Error(`${type}: ${message}`);
  },
};

export const runtime = {
  earlyReturn: (value) => value,
};

