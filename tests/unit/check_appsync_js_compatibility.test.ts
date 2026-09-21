import { describe, test, expect } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { join } from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

const RESOLVERS_DIR = join(
  __dirname,
  "..",
  "..",
  "tofu",
  "application",
  "appsync",
  "js-resolvers",
);

describe("AppSync JS resolvers compatibility checks", () => {
  const files = readdirSync(RESOLVERS_DIR).filter(
    (f) => f.endsWith(".js") && !f.endsWith(".test.js") && !f.endsWith(".mjs"),
  );

  for (const file of files) {
    test(`${file} should not use unsupported APPSYNC_JS constructs`, () => {
      const content = readFileSync(join(RESOLVERS_DIR, file), "utf8");

      // APPSYNC_JS 1.0.0 lacks the Boolean object/function (Boolean(...) is rejected at CreateFunction/CreateResolver)
      expect(content).not.toMatch(/\bBoolean\s*\(/);

      // APPSYNC_JS 1.0.0 lacks Number.isInteger
      expect(content).not.toMatch(/Number\.isInteger/);

      // APPSYNC_JS 1.0.0 rejects continue statements
      expect(content).not.toMatch(/\bcontinue\s*;/);
    });
  }
});
