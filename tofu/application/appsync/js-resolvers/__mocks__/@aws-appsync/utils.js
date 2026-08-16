export const util = {
  dynamodb: {
    toMapValues: (obj) => obj,
  },
  time: {
    nowISO8601: () => '2024-01-01T00:00:00Z',
  },
  error: (message, type) => {
    throw new Error(`${type}: ${message}`);
  },
};

export const runtime = {
  earlyReturn: (value) => value,
};

