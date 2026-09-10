import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './list_my_profiles_pipeline_resolver.js';

describe('list_my_profiles_pipeline_resolver', () => {
    it('returns the connection produced by the pipeline functions', () => {
        const connection = { profiles: [], nextToken: null };
        const ctx = { prev: { result: connection } };

        assert.strictEqual(response(ctx), connection);
    });

    it('throws on pipeline error', () => {
        const ctx = {
            prev: { result: null },
            error: { message: 'boom', type: 'InternalError' },
        };
        assert.throws(() => response(ctx), /InternalError: boom/);
    });

    it('issues an empty request', () => {
        assert.deepStrictEqual(request({}), {});
    });
});
