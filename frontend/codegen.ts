import type { CodegenConfig } from '@graphql-codegen/cli';

/**
 * GraphQL Code Generator Configuration
 *
 * Generates TypeScript types from the GraphQL schema.
 * Run with: npm run codegen
 *
 * The generated types are placed in src/types/graphql-generated.ts
 * and can be imported alongside the manually maintained types in entities.ts.
 */
const config: CodegenConfig = {
  // Path to the GraphQL schema (relative to frontend/)
  schema: '../tofu/application/schema/schema.graphql',

  // Generate types for operations defined in these files
  documents: ['src/**/*.tsx', 'src/**/*.ts', '!src/types/graphql-generated.ts', '!src/lib/test-*.ts'],

  // Output configuration
  generates: {
    // Output file for generated types
    'src/types/graphql-generated.ts': {
      plugins: ['typescript', 'typescript-operations'],
      config: {
        // Use exact optional properties for stricter null checks
        exactOptionalPropertyTypes: false,

        // Skip deprecated GraphQL operations
        skipTypename: false,

        // Use enum as type instead of const (better for runtime use)
        enumsAsTypes: true,

        // AWS-specific scalar mappings
        scalars: {
          AWSDateTime: 'string',
          AWSDate: 'string',
          AWSEmail: 'string',
          AWSPhone: 'string',
          AWSURL: 'string',
          AWSJSON: 'Record<string, unknown>',
        },

        // Avoid naming conflicts with manually maintained types
        // We prefix generated types with 'Gql' to distinguish them
        typesPrefix: 'Gql',

        // Do not add __typename by default to reduce noise
        addUnderscoreToArgsType: true,

        // Use 'Maybe<T>' for nullable types
        maybeValue: 'T | null | undefined',

        // Do not export enum values as const (use type only)
        constEnums: false,
      },
    },
  },

  // Enable hooks for additional processing
  hooks: {
    afterAllFileWrite: ['prettier --write'],
  },

  // Ignore patterns
  ignoreNoDocuments: true,
};

export default config;
